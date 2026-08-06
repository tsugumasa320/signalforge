from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity_curve: pd.Series
    metrics: dict[str, Any]
    journal_run_id: str
    final_cash: float = 0.0
    final_state: dict[str, Any] | None = None


def compute_metrics(trades: pd.DataFrame, equity: pd.Series) -> dict[str, Any]:
    if trades.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "gross_profit_factor": 0.0,
            "total_fees_usd": 0.0,
            "total_slippage_usd": 0.0,
            "total_cost_usd": 0.0,
            "avg_cost_per_trade_usd": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown_pct": 0.0,
            "total_return_pct": 0.0,
            "avg_hold_bars": 0.0,
        }

    wins = trades[trades["pnl_pct"] > 0]
    losses = trades[trades["pnl_pct"] <= 0]
    gross_profit = wins["pnl_pct"].sum() if len(wins) else 0
    gross_loss = abs(losses["pnl_pct"].sum()) if len(losses) else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    gross_pf = pf
    if "gross_pnl_pct" in trades.columns:
        gw = trades[trades["gross_pnl_pct"] > 0]
        gl = trades[trades["gross_pnl_pct"] <= 0]
        gp = gw["gross_pnl_pct"].sum() if len(gw) else 0
        gloss = abs(gl["gross_pnl_pct"].sum()) if len(gl) else 0
        gross_pf = gp / gloss if gloss > 0 else float("inf")

    total_fees = float(trades["total_fees_usd"].sum()) if "total_fees_usd" in trades.columns else 0.0
    total_slippage = float(trades["total_slippage_usd"].sum()) if "total_slippage_usd" in trades.columns else 0.0
    total_cost = float(trades["total_cost_usd"].sum()) if "total_cost_usd" in trades.columns else 0.0

    returns = equity.pct_change().dropna()
    sharpe = 0.0
    sortino = 0.0
    if len(returns) > 1 and returns.std() > 0:
        sharpe = float(returns.mean() / returns.std() * np.sqrt(252))
        downside = returns[returns < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino = float(returns.mean() / downside.std() * np.sqrt(252))

    rolling_max = equity.cummax()
    dd = (equity - rolling_max) / rolling_max
    max_dd = float(dd.min() * 100) if len(dd) else 0.0

    return {
        "total_trades": len(trades),
        "win_rate": float(len(wins) / len(trades)) if len(trades) else 0.0,
        "profit_factor": float(pf) if pf != float("inf") else 999.0,
        "gross_profit_factor": float(gross_pf) if gross_pf != float("inf") else 999.0,
        "total_fees_usd": total_fees,
        "total_slippage_usd": total_slippage,
        "total_cost_usd": total_cost,
        "avg_cost_per_trade_usd": total_cost / len(trades) if len(trades) else 0.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown_pct": max_dd,
        "total_return_pct": float((equity.iloc[-1] / equity.iloc[0] - 1) * 100) if len(equity) > 1 else 0.0,
        "avg_hold_bars": float(trades["hold_bars"].mean()) if "hold_bars" in trades else 0.0,
        "avg_pnl_pct": float(trades["pnl_pct"].mean()),
    }
