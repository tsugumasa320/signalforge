"""Cohort filters and sidecar loading (no scan/dashboard imports — avoids cycles)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signalforge.config import data_dir
from signalforge.experiments.storage import load_ticker_rows

TSE_SEGMENT_LABELS: dict[str, str] = {
    "prime": "プライム",
    "standard": "スタンダード",
    "growth": "グロース",
}


def strategies_dir() -> Path:
    return data_dir() / "reports" / "experiments" / "strategies"


def filter_ticker_rows(
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


def load_ticker_rows_in_dir(
    strategy_id: str,
    doc: dict[str, Any],
    strategies_dir_path: Path | None,
) -> list[dict[str, Any]]:
    if strategies_dir_path is None or strategies_dir_path == strategies_dir():
        return load_ticker_rows(strategy_id, doc)
    inline = doc.get("tickers")
    if inline:
        return list(inline)
    side = doc.get("tickers_file")
    if side:
        path = strategies_dir_path / side
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                return raw if isinstance(raw, list) else []
            except json.JSONDecodeError:
                return []
    path = strategies_dir_path / f"{strategy_id}.tickers.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, list) else []
        except json.JSONDecodeError:
            return []
    return []


def ranking_row_from_aggregate(
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
