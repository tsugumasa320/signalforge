"""Read 5-minute and 1-minute day-trade campaign results side by side."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signalforge.config import data_dir
from signalforge.experiments.checkpoint_meta import read_checkpoint_progress

PRICE_INTRADAY_STRATEGIES = [
    "vwap_ema",
    "vwap_reclaim",
    "orb",
    "vwap_pullback_long",
    "vwap_mean_reversion_short",
    "vwap_breakout_follow",
    "am_high_breakout_volume",
    "pm_high_breakout",
    "relative_volume_filter",
    "opening_gap_daytrade",
    "first_hour_momentum",
    "lunch_break_fade",
    "close_momentum",
    "prior_day_hl_break",
    "pivot_point_bounce",
    "ema9_21_scalp_5m",
    "parabolic_sar_intraday",
    "professional_daytrader_session",
    "vwap_orderflow_itasha",
]

CAMPAIGNS = (
    ("5m", "5分足", "experiments"),
    ("1m", "1分足", "experiments_1m"),
)


def is_price_intraday(strategy_id: str) -> bool:
    return strategy_id in set(PRICE_INTRADAY_STRATEGIES)


def without_intraday(rows: list[dict[str, Any]], *, key: str = "strategy_id") -> list[dict[str, Any]]:
    """Daily campaign rows. The 19 short-bar strategies live in their own tables."""
    return [row for row in rows if not is_price_intraday(str(row.get(key) or ""))]


def campaign_dir(folder: str) -> Path:
    return data_dir() / "reports" / folder


def _load_header(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def intraday_result_rows() -> list[dict[str, Any]]:
    """One row per strategy and bar size. Missing files stay visible as 計算中."""
    rows: list[dict[str, Any]] = []
    for timeframe, label, folder in CAMPAIGNS:
        root = campaign_dir(folder)
        strategies = root / "strategies"
        for sid in PRICE_INTRADAY_STRATEGIES:
            doc = _load_header(strategies / f"{sid}.json")
            progress = read_checkpoint_progress(strategies / f"{sid}.checkpoint.json")
            universe = (doc or {}).get("universe") or {}
            done = int((doc or {}).get("n_tickers_done") or progress.get("n_tickers_done") or 0)
            target = int((doc or {}).get("n_tickers_target") or progress.get("n_tickers_target") or 0)
            complete = bool((doc or {}).get("complete"))
            if complete:
                status = "完了"
            elif done:
                status = f"計算中 {done}/{target or '?'}"
            else:
                status = "未着手"
            rows.append(
                {
                    "timeframe": timeframe,
                    "timeframe_label": label,
                    "strategy_id": sid,
                    "status": status,
                    "window": (doc or {}).get("backtest_window") or "",
                    "n_tickers": universe.get("n_tickers"),
                    "median_return_pct": universe.get("median_total_return_pct"),
                    "median_profit_factor": universe.get("median_profit_factor"),
                    "median_trades": universe.get("median_trades"),
                    "median_win_rate": universe.get("median_win_rate"),
                }
            )
    return rows
