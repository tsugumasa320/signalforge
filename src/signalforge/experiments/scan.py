"""Filesystem scan for TSE experiment campaign progress (CLI + dashboard)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from signalforge.backtest.capital import capital_records_match
from signalforge.compare.runner import _aggregate
from signalforge.config import data_dir, load_web_catalog
from signalforge.experiments.checkpoint_meta import read_checkpoint_progress
from signalforge.experiments.storage import (
    load_ticker_rows,
    rows_for_universe_aggregate,
    ticker_row_has_core_metrics,
)
from signalforge.paper.matrix import paper_portfolio_exists


def _header_metrics_poisoned(header_universe: dict[str, Any]) -> bool:
    exp = header_universe.get("median_avg_pnl_pct")
    return exp is not None and float(exp) <= -20.0


TSE_SEGMENT_LABELS: dict[str, str] = {
    "prime": "プライム",
    "standard": "スタンダード",
    "growth": "グロース",
}


def _filter_ticker_rows(
    rows: list[dict[str, Any]],
    *,
    segment: str | None = None,
    sector_tse: str | None = None,
) -> list[dict[str, Any]]:
    out = rows
    if segment:
        out = [r for r in out if r.get("segment") == segment]
    if sector_tse:
        out = [r for r in out if r.get("sector_tse") == sector_tse]
    return out


def _load_ticker_rows_in_dir(
    strategy_id: str,
    doc: dict[str, Any],
    strategies_dir: Path | None,
) -> list[dict[str, Any]]:
    if strategies_dir is None or strategies_dir == _strategies_dir():
        return load_ticker_rows(strategy_id, doc)
    inline = doc.get("tickers")
    if inline:
        return list(inline)
    side = doc.get("tickers_file")
    if side:
        path = strategies_dir / side
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                return raw if isinstance(raw, list) else []
            except json.JSONDecodeError:
                return []
    path = strategies_dir / f"{strategy_id}.tickers.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _cohort_from_valid_sidecar(
    strategy_id: str,
    doc: dict[str, Any],
    header_group: dict[str, Any],
    *,
    segment: str | None = None,
    sector_tse: str | None = None,
    strategies_dir: Path | None = None,
) -> tuple[dict[str, Any], int, int]:
    """Prefer live aggregate from sidecar rows with valid 期待値/DD (during metric refresh)."""
    rows = _load_ticker_rows_in_dir(strategy_id, doc, strategies_dir)
    ok = _filter_ticker_rows([r for r in rows if not r.get("error")], segment=segment, sector_tse=sector_tse)
    valid = [r for r in ok if ticker_row_has_core_metrics(r)]
    n_valid = len(valid)
    min_show = 5
    if n_valid >= min_show:
        return _aggregate(valid), n_valid, len(ok)
    if _header_metrics_poisoned(header_group):
        return {}, n_valid, len(ok)
    exp = header_group.get("median_avg_pnl_pct")
    if exp is not None and float(exp) > -20.0:
        return header_group, n_valid, len(ok)
    agg_rows = rows_for_universe_aggregate(ok)
    if agg_rows:
        return _aggregate(agg_rows), n_valid, len(ok)
    return {}, n_valid, len(ok)


def _universe_from_valid_sidecar(
    strategy_id: str,
    doc: dict[str, Any],
    header_universe: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    return _cohort_from_valid_sidecar(strategy_id, doc, header_universe)


def _ranking_row_from_aggregate(
    base: dict[str, Any],
    u: dict[str, Any],
    *,
    n_valid: int,
    n_ok: int,
) -> dict[str, Any]:
    return {
        **base,
        "expectancy_pct": u.get("median_avg_pnl_pct"),
        "profit_factor": u.get("median_profit_factor"),
        "win_rate": u.get("median_win_rate"),
        "total_trades": u.get("median_trades"),
        "max_drawdown_pct": u.get("median_max_drawdown_pct"),
        "n_tickers": u.get("n_tickers"),
        "metrics_valid_tickers": n_valid,
        "metrics_total_tickers": n_ok,
        "metrics_partial": n_valid < n_ok,
    }


def list_campaign_sectors(*, strategies_dir: Path | None = None) -> list[str]:
    d = strategies_dir or _strategies_dir()
    sectors: set[str] = set()
    if not d.is_dir():
        return []
    for path in sorted(d.glob("*.json")):
        if path.name.endswith(".tickers.json") or path.name.endswith(".checkpoint.json"):
            continue
        doc = _load_json(path)
        if not doc or not doc.get("complete"):
            continue
        for sec in (doc.get("by_sector") or {}):
            if sec:
                sectors.add(str(sec))
    return sorted(sectors)


def apply_cohort_to_complete(
    complete: list[dict[str, Any]],
    *,
    segment: str | None = None,
    sector_tse: str | None = None,
    strategies_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Rebuild ranking rows for Prime / Standard / Growth / sector cohorts."""
    if not segment and not sector_tse:
        return list(complete)
    d = strategies_dir or _strategies_dir()
    out: list[dict[str, Any]] = []
    for base in complete:
        sid = str(base.get("strategy_id") or "")
        path = d / f"{sid}.json"
        doc = _load_json(path)
        if not doc:
            continue
        if segment:
            header = (doc.get("by_segment") or {}).get(segment) or {}
        else:
            header = (doc.get("by_sector") or {}).get(sector_tse or "") or {}
        u, n_valid, n_ok = _cohort_from_valid_sidecar(
            sid,
            doc,
            header,
            segment=segment,
            sector_tse=sector_tse,
            strategies_dir=d,
        )
        if not u and n_ok == 0:
            continue
        keep = {
            k: base[k]
            for k in ("strategy_id", "style", "capital_ok", "paper_active", "mtime")
            if k in base
        }
        out.append(_ranking_row_from_aggregate(keep, u, n_valid=n_valid, n_ok=n_ok))
    out.sort(
        key=lambda x: float(x.get("expectancy_pct") or x.get("profit_factor") or 0),
        reverse=True,
    )
    return out


def _strategies_dir() -> Path:
    return data_dir() / "reports" / "experiments" / "strategies"


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def planned_strategy_count() -> int:
    return sum(
        1
        for s in load_web_catalog().get("strategies", [])
        if s.get("implemented") and s.get("id")
    )


def scan_campaign_progress(*, strategies_dir: Path | None = None) -> dict[str, Any]:
    d = strategies_dir or _strategies_dir()
    complete: list[dict[str, Any]] = []
    in_progress: list[dict[str, Any]] = []
    total_planned = planned_strategy_count()

    manifest_path = data_dir() / "reports" / "experiments" / "manifest.json"
    manifest = _load_json(manifest_path) or {}
    manifest_cap = manifest.get("backtest_capital") if isinstance(manifest.get("backtest_capital"), dict) else None

    if not d.is_dir():
        return {
            "complete": complete,
            "in_progress": in_progress,
            "total_planned": total_planned,
            "n_tickers_pool": None,
            "manifest": manifest,
        }

    for path in sorted(d.glob("*.json")):
        if path.name.endswith(".tickers.json"):
            continue
        if path.name.endswith(".checkpoint.json"):
            if not path.exists():
                continue
            sid = path.name.replace(".checkpoint.json", "")
            prog = read_checkpoint_progress(path)
            if prog["n_tickers_target"] <= 0 and prog["n_tickers_done"] <= 0:
                continue
            in_progress.append(
                {
                    "strategy_id": sid,
                    "n_done": prog["n_tickers_done"],
                    "n_target": prog["n_tickers_target"],
                    "source": "checkpoint",
                    "mtime": _safe_mtime(path),
                }
            )
            continue
        if path.name.endswith(".checkpoint.tickers.json"):
            continue
        doc = _load_json(path)
        if not doc or doc.get("error"):
            continue
        sid = str(doc.get("strategy_id") or path.stem)
        target = int(doc.get("n_tickers_target") or 0)
        done = int(doc.get("n_tickers_done") or 0)
        if doc.get("complete") and target > 0 and done >= target:
            header_u = doc.get("universe") or {}
            u, n_valid, n_ok = _universe_from_valid_sidecar(sid, doc, header_u)
            stored_cap = doc.get("backtest_capital")
            if manifest_cap and isinstance(stored_cap, dict):
                cap_ok = capital_records_match(stored_cap, manifest_cap)
            else:
                cap_ok = stored_cap is not None
            complete.append(
                {
                    "strategy_id": sid,
                    "style": doc.get("style"),
                    "expectancy_pct": u.get("median_avg_pnl_pct"),
                    "profit_factor": u.get("median_profit_factor"),
                    "win_rate": u.get("median_win_rate"),
                    "total_trades": u.get("median_trades"),
                    "max_drawdown_pct": u.get("median_max_drawdown_pct"),
                    "n_tickers": u.get("n_tickers"),
                    "metrics_valid_tickers": n_valid,
                    "metrics_total_tickers": n_ok,
                    "metrics_partial": n_valid < n_ok,
                    "capital_ok": cap_ok,
                    "paper_active": paper_portfolio_exists(sid),
                    "mtime": _safe_mtime(path),
                }
            )
        elif done > 0 and not doc.get("complete"):
            in_progress.append(
                {
                    "strategy_id": sid,
                    "n_done": done,
                    "n_target": target or done,
                    "source": "partial",
                    "mtime": _safe_mtime(path),
                }
            )

    complete.sort(
        key=lambda x: float(x.get("expectancy_pct") or x.get("profit_factor") or 0),
        reverse=True,
    )
    # Prefer checkpoint row when both exist for same strategy
    by_sid: dict[str, dict[str, Any]] = {}
    for row in in_progress:
        sid = row["strategy_id"]
        prev = by_sid.get(sid)
        if prev is None or row.get("n_done", 0) >= prev.get("n_done", 0):
            by_sid[sid] = row
    in_progress = sorted(by_sid.values(), key=lambda r: r.get("strategy_id", ""))
    if in_progress:
        latest_mtime = max(float(r.get("mtime") or 0) for r in in_progress)
        for row in in_progress:
            row["active"] = float(row.get("mtime") or 0) >= latest_mtime - 1.0

    targets = [int(r.get("n_target") or 0) for r in in_progress if int(r.get("n_target") or 0) > 0]
    man_n = int(manifest.get("n_tickers") or 0)
    if targets:
        pool = max(targets)
    elif man_n > 50:
        pool = man_n
    elif complete:
        pool = complete[0].get("n_tickers")
    else:
        pool = man_n or None

    out = {
        "complete": complete,
        "in_progress": in_progress,
        "total_planned": total_planned,
        "n_tickers_pool": pool,
        "manifest": manifest,
    }
    out["overall"] = summarize_campaign_progress(out)
    return out


def apply_cohort_period_slice(
    complete: list[dict[str, Any]],
    *,
    start: date | None,
    end: date | None,
    segment: str | None = None,
    sector_tse: str | None = None,
    strategies_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rebuild ranking from trades_compact / equity_daily (no re-backtest)."""
    from signalforge.experiments.series import (
        aggregate_sliced_rows,
        slice_row_metrics,
        strategy_series_coverage,
        ticker_row_has_series,
    )

    if start is None:
        return [], {"n_strategies": 0, "series_tickers": 0, "total_tickers": 0}
    d = strategies_dir or _strategies_dir()
    out: list[dict[str, Any]] = []
    series_tickers = 0
    total_tickers = 0
    for base in complete:
        sid = str(base.get("strategy_id") or "")
        path = d / f"{sid}.json"
        doc = _load_json(path)
        if not doc:
            continue
        rows = _load_ticker_rows_in_dir(sid, doc, d)
        ok = _filter_ticker_rows(
            [r for r in rows if not r.get("error")],
            segment=segment,
            sector_tse=sector_tse,
        )
        n_series, n_ok = strategy_series_coverage(ok)
        total_tickers += n_ok
        series_tickers += n_series
        sliced: list[dict[str, Any]] = []
        for r in ok:
            if not ticker_row_has_series(r):
                continue
            sm = slice_row_metrics(r, start, end)
            if sm:
                sliced.append({**r, **sm})
        if not sliced:
            continue
        u = aggregate_sliced_rows(sliced)
        n_valid = sum(1 for r in sliced if ticker_row_has_core_metrics(r))
        keep = {
            k: base[k]
            for k in ("strategy_id", "style", "capital_ok", "paper_active", "mtime")
            if k in base
        }
        out.append(_ranking_row_from_aggregate(keep, u, n_valid=n_valid, n_ok=len(sliced)))
    out.sort(
        key=lambda x: float(x.get("expectancy_pct") or x.get("profit_factor") or 0),
        reverse=True,
    )
    meta = {
        "n_strategies": len(out),
        "series_tickers": series_tickers,
        "total_tickers": total_tickers,
    }
    return out, meta


def summarize_campaign_progress(scan: dict[str, Any]) -> dict[str, Any]:
    """Human-friendly rollup for CLI watch/status."""
    n_plan = int(scan.get("total_planned") or 0)
    pool = int(scan.get("n_tickers_pool") or 0)
    n_complete = len(scan.get("complete") or [])
    in_prog = scan.get("in_progress") or []

    active_rows = [r for r in in_prog if r.get("active")]
    stale_rows = [r for r in in_prog if not r.get("active")]

    partial_equiv = 0.0
    active = active_rows[0] if active_rows else None
    if active:
        tgt = max(1, int(active.get("n_target") or pool or 1))
        partial_equiv = int(active.get("n_done") or 0) / tgt

    strategy_equiv = n_complete + partial_equiv
    strategy_pct = 100.0 * strategy_equiv / n_plan if n_plan else 0.0

    ticker_done = n_complete * pool if pool else 0
    if active and pool:
        ticker_done += int(active.get("n_done") or 0)
    ticker_total = n_plan * pool if pool and n_plan else 0
    ticker_pct = 100.0 * ticker_done / ticker_total if ticker_total else 0.0

    return {
        "strategies_complete": n_complete,
        "strategies_planned": n_plan,
        "strategy_equiv": strategy_equiv,
        "strategy_overall_pct": strategy_pct,
        "ticker_jobs_done": ticker_done,
        "ticker_jobs_total": ticker_total,
        "ticker_overall_pct": ticker_pct,
        "active_strategy_id": active.get("strategy_id") if active else None,
        "active_n_done": int(active.get("n_done") or 0) if active else 0,
        "active_n_target": int(active.get("n_target") or pool or 0) if active else 0,
        "stale_checkpoints": [
            {
                "strategy_id": r.get("strategy_id"),
                "n_done": int(r.get("n_done") or 0),
                "n_target": int(r.get("n_target") or pool or 0),
            }
            for r in stale_rows
        ],
    }


def format_progress_bar(pct: float, width: int = 32) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100.0))
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct:5.1f}%"
