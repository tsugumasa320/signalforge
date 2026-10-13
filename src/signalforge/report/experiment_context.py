"""TSE experiment premises, filters, paper vs backtest — dashboard helpers."""

from __future__ import annotations

from datetime import datetime, timezone
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
    from signalforge.paper.matrix import PAPER_SIMULATIONS
    from signalforge.report.static_dashboard import paper_summary_row

    for style, strat in PAPER_SIMULATIONS:
        if strat != strategy_id:
            continue
        row = paper_summary_row(style, strategy_id, refresh=False)
        if row:
            row["style"] = style
            return row
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


def live_strategy_universe(strategy_id: str, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dashboard 用: 毒データを除いた universe 集計。"""
    from signalforge.compare.runner import _aggregate
    from signalforge.experiments.storage import (
        load_strategy_header,
        load_ticker_rows,
        rows_for_universe_aggregate,
    )

    doc = doc or load_strategy_header(strategy_id) or {}
    header = doc.get("universe") or {}
    ok = [r for r in load_ticker_rows(strategy_id, doc) if not r.get("error")]
    valid = rows_for_universe_aggregate(ok)
    header_exp = header.get("median_avg_pnl_pct")
    poisoned = header_exp is not None and float(header_exp) <= -20.0
    if len(valid) >= 5 or (poisoned and len(valid) >= 1):
        return _aggregate(valid)
    exp = header.get("median_avg_pnl_pct")
    if exp is not None and float(exp) > -20.0:
        return header
    return {}


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
