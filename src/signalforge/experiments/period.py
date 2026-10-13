"""On-demand experiment rollups for custom backtest windows (dashboard / CLI helpers)."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Callable

from signalforge.compare.runner import _aggregate, resolve_strategy_style, run_cohort_backtests
from signalforge.config import data_dir, load_backtest_defaults, load_web_catalog
from signalforge.experiments.runner import load_plan, resolve_campaign_backtest_capital
from signalforge.experiments.scan import (
    _filter_ticker_rows,
    _load_ticker_rows_in_dir,
    _ranking_row_from_aggregate,
    _strategies_dir,
)
from signalforge.experiments.storage import load_strategy_header, rows_for_universe_aggregate


def experiments_dir() -> Path:
    return data_dir() / "reports" / "experiments"


def period_cache_dir() -> Path:
    d = experiments_dir() / "period_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_date(raw: Any) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()[:10]
    if not s:
        return None
    return date.fromisoformat(s)


def normalize_period_end(end: date | None) -> date | None:
    return end


def periods_match(
    a_start: date | None,
    a_end: date | None,
    b_start: date | None,
    b_end: date | None,
) -> bool:
    if a_start != b_start:
        return False
    ae = normalize_period_end(a_end)
    be = normalize_period_end(b_end)
    return ae == be


def infer_stored_backtest_period(
    complete: list[dict[str, Any]] | None = None,
    *,
    strategies_dir: Path | None = None,
) -> tuple[date, date | None]:
    """Typical backtest window from saved ticker sidecars (fallback: config default)."""
    d = strategies_dir or _strategies_dir()
    for base in complete or []:
        sid = str(base.get("strategy_id") or "")
        doc = load_strategy_header(sid)
        if not doc:
            path = d / f"{sid}.json"
            if path.exists():
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    doc = None
        if not doc:
            continue
        rows = _load_ticker_rows_in_dir(sid, doc, d)
        for row in rows:
            start = _parse_date(row.get("backtest_start"))
            if start is None:
                continue
            return start, _parse_date(row.get("backtest_end"))
    defaults = load_backtest_defaults()
    start_s = defaults.get("backtest_start_date", "2023-01-01")
    return date.fromisoformat(str(start_s)[:10]), None


def period_label(start: date | None, end: date | None) -> str:
    s = start.isoformat() if start else "—"
    e = end.isoformat() if end else "最新"
    return f"{s} 〜 {e}"


def period_cache_key(
    start: date | None,
    end: date | None,
    *,
    segment: str | None = None,
    sector_tse: str | None = None,
) -> str:
    raw = "|".join(
        [
            start.isoformat() if start else "",
            end.isoformat() if end else "",
            segment or "",
            sector_tse or "",
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def load_period_cache(key: str) -> dict[str, Any] | None:
    path = period_cache_dir() / f"{key}.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def save_period_cache(key: str, payload: dict[str, Any]) -> None:
    path = period_cache_dir() / f"{key}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cfg_override_for_period(
    start: date | None,
    end: date | None,
    *,
    base_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = dict(base_override or {})
    if start or end:
        bt = dict(out.get("backtest") or {})
        if start:
            bt["start_date"] = start.isoformat()
        if end:
            bt["end_date"] = end.isoformat()
        out["backtest"] = bt
    return out


def cohort_ticker_symbols(
    strategy_id: str,
    doc: dict[str, Any],
    *,
    segment: str | None = None,
    sector_tse: str | None = None,
    strategies_dir: Path | None = None,
) -> list[str]:
    rows = _load_ticker_rows_in_dir(strategy_id, doc, strategies_dir)
    ok = _filter_ticker_rows(
        [r for r in rows if not r.get("error")],
        segment=segment,
        sector_tse=sector_tse,
    )
    seen: set[str] = set()
    out: list[str] = []
    for r in ok:
        sym = r.get("ticker")
        if sym and sym not in seen:
            seen.add(str(sym))
            out.append(str(sym))
    return out


def rollup_strategy_period(
    strategy_id: str,
    *,
    start: date | None,
    end: date | None,
    segment: str | None = None,
    sector_tse: str | None = None,
    cost_model: str = "japan",
    max_workers: int = 4,
    strategies_dir: Path | None = None,
) -> dict[str, Any] | None:
    doc = load_strategy_header(strategy_id)
    if not doc or not doc.get("complete"):
        return None
    tickers = cohort_ticker_symbols(
        strategy_id,
        doc,
        segment=segment,
        sector_tse=sector_tse,
        strategies_dir=strategies_dir,
    )
    if not tickers:
        return None
    catalog = {s["id"]: s for s in load_web_catalog().get("strategies", []) if s.get("id")}
    style = resolve_strategy_style(strategy_id, catalog)
    _, cap_override = resolve_campaign_backtest_capital(load_plan())
    cfg_override = cfg_override_for_period(start, end, base_override=cap_override)
    block = run_cohort_backtests(
        strategy_id=strategy_id,
        style=style,
        tickers=tickers,
        cost_model=cost_model,
        refresh=False,
        cfg_override=cfg_override,
        max_workers=max_workers,
        existing_rows=None,
        bulk_mode=True,
    )
    rows = [r for r in block.get("tickers") or [] if not r.get("error")]
    valid = rows_for_universe_aggregate(rows)
    u = _aggregate(valid if valid else rows)
    n_valid = len(valid)
    base = {
        "strategy_id": strategy_id,
        "style": doc.get("style") or style,
    }
    row = _ranking_row_from_aggregate(base, u, n_valid=n_valid, n_ok=len(rows))
    row["period_start"] = start.isoformat() if start else None
    row["period_end"] = end.isoformat() if end else None
    row["period_label"] = period_label(start, end)
    return row


def aggregate_from_ranking_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "n_tickers": row.get("n_tickers"),
        "median_profit_factor": row.get("profit_factor"),
        "median_win_rate": row.get("win_rate"),
        "median_trades": row.get("total_trades"),
        "median_avg_pnl_pct": row.get("expectancy_pct"),
        "median_max_drawdown_pct": row.get("max_drawdown_pct"),
    }


def rollup_complete_for_period(
    complete: list[dict[str, Any]],
    *,
    start: date | None,
    end: date | None,
    segment: str | None = None,
    sector_tse: str | None = None,
    cost_model: str = "japan",
    max_workers: int = 4,
    progress_cb: Callable[[int, int, str], None] | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Re-backtest all complete strategies for a custom window (uses disk cache)."""
    key = period_cache_key(start, end, segment=segment, sector_tse=sector_tse)
    if use_cache:
        cached = load_period_cache(key)
        if cached and cached.get("rows"):
            rows = cached["rows"]
            if isinstance(rows, list):
                by_sid = {str(r.get("strategy_id")): r for r in rows if r.get("strategy_id")}
                out = []
                for base in complete:
                    sid = str(base.get("strategy_id") or "")
                    if sid in by_sid:
                        merged = {**base, **by_sid[sid]}
                        out.append(merged)
                out.sort(
                    key=lambda x: float(x.get("expectancy_pct") or x.get("profit_factor") or 0),
                    reverse=True,
                )
                return out

    manifest_path = experiments_dir() / "manifest.json"
    cost = cost_model
    if manifest_path.exists():
        try:
            man = json.loads(manifest_path.read_text(encoding="utf-8"))
            cost = str(man.get("cost_model") or cost)
        except json.JSONDecodeError:
            pass

    total = len(complete)
    out_rows: list[dict[str, Any]] = []
    for i, base in enumerate(complete, start=1):
        sid = str(base.get("strategy_id") or "")
        if progress_cb:
            progress_cb(i, total, sid)
        row = rollup_strategy_period(
            sid,
            start=start,
            end=end,
            segment=segment,
            sector_tse=sector_tse,
            cost_model=cost,
            max_workers=max_workers,
        )
        if row:
            merged = {**base, **row}
            out_rows.append(merged)

    out_rows.sort(
        key=lambda x: float(x.get("expectancy_pct") or x.get("profit_factor") or 0),
        reverse=True,
    )
    if use_cache and out_rows:
        save_period_cache(
            key,
            {
                "period": {
                    "start": start.isoformat() if start else None,
                    "end": end.isoformat() if end else None,
                    "segment": segment,
                    "sector_tse": sector_tse,
                    "label": period_label(start, end),
                },
                "rows": out_rows,
            },
        )
    return out_rows
