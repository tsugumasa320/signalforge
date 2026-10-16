"""TSE experiment premises, filters, paper vs backtest — dashboard helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.backtest.capital import (
    backtest_capital_record,
    capital_records_match,
    resolve_experiment_capital,
)
from signalforge.config import data_dir, load_backtest_defaults, load_web_catalog, project_root
from signalforge.experiments.runner import load_plan


def experiment_premises(manifest: dict[str, Any] | None = None) -> dict[str, str]:
    """Human-readable backtest assumptions for the TSE campaign."""
    plan = load_plan()
    meta = plan.get("meta") or {}
    manifest = manifest or {}
    defaults = load_backtest_defaults()
    start = str(defaults.get("backtest_start_date") or "2023-01-01")
    cost = str(meta.get("cost_model") or manifest.get("cost_model") or "japan")
    n_tickers = manifest.get("n_tickers")
    finished = manifest.get("finished_at") or manifest.get("started_at")

    listing = data_dir() / "universe" / "tse_listing.json"
    if not listing.exists():
        listing = project_root() / "data" / "universe" / "tse_listing.json"
    data_as_of = "—"
    if listing.exists():
        ts = datetime.fromtimestamp(listing.stat().st_mtime, tz=timezone.utc).astimezone()
        data_as_of = ts.strftime("%Y-%m-%d")

    return {
        "評価開始": start + " 〜 最新OHLCV",
        "コストモデル": cost + "（config/costs + スリッページ）",
        "約定": "翌日始値（style: fill=next_day_open）· 銘柄ごと独立口座・1回フル投入",
        "ユニバース": f"東証内国株式 {n_tickers or '〜3520'} 銘柄",
        "銘柄リスト": f"更新目安 {data_as_of}",
        "集計更新": (str(finished)[:19] if finished else "—"),
    }


def capital_compare_presets() -> list[dict[str, Any]]:
    """Named capital scenarios for re-backtest (config + built-in fallback)."""
    plan = load_plan()
    meta = plan.get("meta") or {}
    raw = meta.get("capital_compare_presets")
    if isinstance(raw, list) and raw:
        return [p for p in raw if isinstance(p, dict) and p.get("label")]
    current = backtest_capital_record(resolve_experiment_capital())
    return [
        {"id": "current", "label": "現在の既定", **{k: current[k] for k in current}},
        {
            "id": "full_deploy",
            "label": "同一口座・全額上限",
            "initial_cash_jpy": current.get("initial_cash_jpy", 3_000_000),
            "max_position_pct": 1.0,
            "min_cash_reserve_pct": 0.0,
            "currency": "JPY",
        },
    ]


def preset_capital_record(preset: dict[str, Any]) -> dict[str, Any]:
    keys = ("initial_cash_jpy", "max_position_pct", "min_cash_reserve_pct")
    overrides = {k: preset[k] for k in keys if preset.get(k) is not None}
    return backtest_capital_record(resolve_experiment_capital(**overrides))


def strategies_matching_capital(
    strategy_ids: list[str],
    target: dict[str, Any],
) -> tuple[int, int]:
    """Return (match_count, total_complete)."""
    from signalforge.experiments.storage import load_strategy_header

    total = 0
    match = 0
    for sid in strategy_ids:
        doc = load_strategy_header(sid)
        if not doc or not doc.get("complete"):
            continue
        total += 1
        stored = doc.get("backtest_capital")
        if isinstance(stored, dict) and capital_records_match(stored, target):
            match += 1
    return match, total


def paper_forward_summary(strategy_id: str) -> dict[str, Any] | None:
    from signalforge.paper.diversified import DiversifiedPaperBook
    from signalforge.paper.matrix import DIVERSIFIED_PAPER_SIMULATIONS
    from signalforge.report.static_dashboard import diversified_paper_summary_row

    for spec in DIVERSIFIED_PAPER_SIMULATIONS:
        if spec.strategy != strategy_id:
            continue
        book = DiversifiedPaperBook.load(spec.style, spec.strategy)
        if book:
            return diversified_paper_summary_row(book)
    return None


def catalog_style_for(strategy_id: str) -> str | None:
    for s in load_web_catalog().get("strategies", []):
        if s.get("id") == strategy_id:
            return s.get("style")
    return None


def default_capital_slider_values(
    manifest_capital: dict[str, Any] | None = None,
) -> tuple[int, float, float]:
    from signalforge.experiments.runner import resolve_campaign_backtest_capital

    rec, _ = resolve_campaign_backtest_capital()
    if manifest_capital:
        rec = {**rec, **{k: v for k, v in manifest_capital.items() if v is not None}}
    return (
        int(rec.get("initial_cash_jpy") or 3_000_000),
        float(rec.get("max_position_pct") or 1.0),
        float(rec.get("min_cash_reserve_pct") or 0.0),
    )


def capital_record_from_ui(
    initial_cash_jpy: int,
    max_position_pct: float,
    min_cash_reserve_pct: float,
) -> dict[str, Any]:
    from signalforge.backtest.capital import backtest_capital_record, resolve_experiment_capital

    policy = resolve_experiment_capital(
        initial_cash_jpy=float(initial_cash_jpy),
        max_position_pct=max_position_pct,
        min_cash_reserve_pct=min_cash_reserve_pct,
    )
    return backtest_capital_record(policy)


def format_capital_rerun_command(record: dict[str, Any]) -> str:
    cash = int(record.get("initial_cash_jpy") or 0)
    pct = float(record.get("max_position_pct") or 1)
    reserve = float(record.get("min_cash_reserve_pct") or 0)
    return (
        f"INITIAL_CASH_JPY={cash} MAX_POSITION_PCT={pct} MIN_CASH_RESERVE_PCT={reserve} "
        f"./scripts/rerun-experiments-capital.sh"
    )


def live_strategy_universe(
    strategy_id: str,
    doc: dict[str, Any] | None = None,
    *,
    segment: str | None = None,
    sector_tse: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    stored_period: tuple[date, date | None] | None = None,
) -> dict[str, Any]:
    """Dashboard 用: 毒データを除いた集計（全体 / 市場区分 / 業種 / 期間）。"""
    from signalforge.experiments.period import infer_stored_backtest_period, periods_match
    from signalforge.experiments.scan import _cohort_from_valid_sidecar
    from signalforge.experiments.storage import load_strategy_header

    doc = doc or load_strategy_header(strategy_id) or {}
    ref_start, ref_end = stored_period or infer_stored_backtest_period(
        [{"strategy_id": strategy_id}]
    )
    ps = period_start if period_start is not None else ref_start
    pe = period_end
    if period_start is None and period_end is None:
        use_stored_period = True
    else:
        use_stored_period = periods_match(ps, pe, ref_start, ref_end)

    if not use_stored_period:
        from signalforge.experiments.ticker_cohort import (
            filter_ticker_rows as _filter_ticker_rows,
            load_ticker_rows_in_dir as _load_ticker_rows_in_dir,
            strategies_dir as _strategies_dir,
        )
        from signalforge.experiments.series import (
            aggregate_sliced_rows,
            period_sliceable,
            slice_row_metrics,
            ticker_row_has_series,
        )

        if not period_sliceable(ps, pe, ref_start, ref_end):
            return {}
        doc = doc or load_strategy_header(strategy_id) or {}
        rows = _load_ticker_rows_in_dir(strategy_id, doc, _strategies_dir())
        ok = _filter_ticker_rows(
            [r for r in rows if not r.get("error")],
            segment=segment,
            sector_tse=sector_tse,
        )
        sliced: list[dict[str, Any]] = []
        for r in ok:
            if not ticker_row_has_series(r):
                continue
            sm = slice_row_metrics(r, ps, pe)
            if sm:
                sliced.append({**r, **sm})
        if sliced:
            return aggregate_sliced_rows(sliced)
        return {}

    if segment:
        header = (doc.get("by_segment") or {}).get(segment) or {}
    elif sector_tse:
        header = (doc.get("by_sector") or {}).get(sector_tse) or {}
    else:
        header = doc.get("universe") or {}
    u, _, _ = _cohort_from_valid_sidecar(
        strategy_id,
        doc,
        header,
        segment=segment,
        sector_tse=sector_tse,
    )
    return u


def live_strategy_breakdown(
    strategy_id: str,
    doc: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """市場区分・業種別の典型値（sidecar から再集計）。"""
    from signalforge.experiments.runner import _aggregate_group
    from signalforge.experiments.storage import (
        load_strategy_header,
        load_ticker_rows,
        rows_for_universe_aggregate,
    )

    doc = doc or load_strategy_header(strategy_id) or {}
    ok = rows_for_universe_aggregate(
        [r for r in load_ticker_rows(strategy_id, doc) if not r.get("error")]
    )
    return _aggregate_group(ok, "segment"), _aggregate_group(ok, "sector_tse")


def apply_ranking_filters(
    df: pd.DataFrame,
    *,
    min_median_trades: float = 0,
    profit_factor_gt_1: bool = False,
    expectancy_positive: bool = False,
    capital_current_only: bool = False,
    manifest_capital: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if min_median_trades > 0 and "total_trades" in out.columns:
        out = out[out["total_trades"].fillna(0) >= min_median_trades]
    if profit_factor_gt_1 and "profit_factor" in out.columns:
        out = out[out["profit_factor"].fillna(0) > 1.0]
    if expectancy_positive and "expectancy_pct" in out.columns:
        out = out[out["expectancy_pct"].fillna(-1e9) > 0]
    if capital_current_only and manifest_capital and "strategy_id" in out.columns:
        from signalforge.experiments.storage import load_strategy_header

        keep: list[str] = []
        for sid in out["strategy_id"].astype(str):
            doc = load_strategy_header(sid) or {}
            stored = doc.get("backtest_capital")
            if isinstance(stored, dict) and capital_records_match(stored, manifest_capital):
                keep.append(sid)
        out = out[out["strategy_id"].astype(str).isin(keep)]
    return out
