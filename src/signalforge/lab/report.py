from __future__ import annotations

import statistics
from typing import Any

import pandas as pd


def izanami_metrics(trades: pd.DataFrame, *, calendar_days: int | None = None) -> dict[str, Any]:
    """Result summary aligned with Izanami backtest report concepts."""
    if trades.empty:
        return {
            "total_signals": 0,
            "total_trades": 0,
            "win_rate": 0.0,
            "expectancy_pct": 0.0,
            "median_pnl_pct": 0.0,
            "profit_factor": 0.0,
            "avg_hold_bars": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "pnl_buckets": {},
        }

    pnl = trades["pnl_pct"].astype(float)
    wins = trades[pnl > 0]
    losses = trades[pnl <= 0]
    gross_profit = float(wins["pnl_pct"].sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses["pnl_pct"].sum())) if len(losses) else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

    buckets = {
        "lte_-5": int((pnl <= -5).sum()),
        "m5_m2": int(((pnl > -5) & (pnl <= -2)).sum()),
        "m2_0": int(((pnl > -2) & (pnl <= 0)).sum()),
        "0_2": int(((pnl > 0) & (pnl <= 2)).sum()),
        "2_5": int(((pnl > 2) & (pnl <= 5)).sum()),
        "gt_5": int((pnl > 5).sum()),
    }

    out: dict[str, Any] = {
        "total_signals": len(trades),
        "total_trades": len(trades),
        "win_rate": float(len(wins) / len(trades)),
        "expectancy_pct": float(pnl.mean()),
        "median_pnl_pct": float(pnl.median()),
        "profit_factor": float(pf) if pf != 999.0 else 999.0,
        "avg_hold_bars": float(trades["hold_bars"].mean()) if "hold_bars" in trades else 0.0,
        "avg_win_pct": float(wins["pnl_pct"].mean()) if len(wins) else 0.0,
        "avg_loss_pct": float(losses["pnl_pct"].mean()) if len(losses) else 0.0,
        "pnl_buckets": buckets,
    }
    if calendar_days and calendar_days > 0:
        out["expectancy_per_day_pct"] = out["expectancy_pct"] * out["total_trades"] / calendar_days
    return out


def aggregate_ticker_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool trades across tickers for cohort-level summary."""
    frames = [pd.DataFrame(r["trades"]) for r in rows if r.get("trades")]
    if not frames:
        return izanami_metrics(pd.DataFrame())
    all_trades = pd.concat(frames, ignore_index=True)
    days = None
    if rows and rows[0].get("calendar_days"):
        days = int(rows[0]["calendar_days"])
    summary = izanami_metrics(all_trades, calendar_days=days)
    summary["tickers_ok"] = sum(1 for r in rows if not r.get("error"))
    summary["tickers_err"] = sum(1 for r in rows if r.get("error"))
    return summary
