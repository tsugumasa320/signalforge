"""Capital-unconstrained rule study (Izanami backtest stage). Each signal → independent trade."""

from __future__ import annotations

from typing import Any

import pandas as pd


def simulate_rule_study_longs(
    df: pd.DataFrame,
    signals: pd.Series,
    *,
    max_hold: int = 15,
    atr_tp: float = 3.0,
    atr_sl: float = 1.5,
    slippage_pct: float = 0.0005,
) -> pd.DataFrame:
    """Evaluate every long signal independently (no overlapping capital constraint)."""
    rows: list[dict[str, Any]] = []
    n = len(df)
    if n < 3:
        return pd.DataFrame()

    for sig_i in range(n - 2):
        if int(signals.iloc[sig_i]) <= 0:
            continue
        entry_idx = sig_i + 1
        if entry_idx >= n:
            break
        entry_open = float(df.iloc[entry_idx]["open"])
        entry_price = entry_open * (1 + slippage_pct)
        atr = float(df.iloc[entry_idx].get("atr_14") or 0)
        if atr <= 0:
            atr = entry_price * 0.02
        tp = entry_price + atr * atr_tp
        sl = entry_price - atr * atr_sl

        exit_idx = None
        exit_price = None
        reason = "max_hold"
        last_check = min(entry_idx + max_hold, n - 1)

        for j in range(entry_idx, last_check + 1):
            row = df.iloc[j]
            if float(row["high"]) >= tp:
                exit_idx = j
                exit_price = tp * (1 - slippage_pct)
                reason = "take_profit"
                break
            if float(row["low"]) <= sl:
                exit_idx = j
                exit_price = sl * (1 - slippage_pct)
                reason = "stop_loss"
                break

        if exit_idx is None:
            exit_idx = last_check
            exit_price = float(df.iloc[exit_idx]["close"]) * (1 - slippage_pct)
            reason = "max_hold"

        pnl_pct = (exit_price - entry_price) / entry_price * 100
        rows.append(
            {
                "signal_time": df.index[sig_i],
                "entry_time": df.index[entry_idx],
                "exit_time": df.index[exit_idx],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_pct": pnl_pct,
                "hold_bars": exit_idx - entry_idx,
                "reason": reason,
            }
        )

    return pd.DataFrame(rows)
