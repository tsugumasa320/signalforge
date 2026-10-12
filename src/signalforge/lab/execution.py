"""Trade simulation with fill / unfilled tracking (Izanami-style)."""

from __future__ import annotations

from typing import Any

import pandas as pd

def _is_stop_limit_block(prev_close: float, open_price: float, side: str = "long") -> bool:
    """JP-style simplified: gap beyond ±10% from prev close → limit not filled."""
    if prev_close <= 0:
        return False
    limit_up = prev_close * 1.1
    limit_down = prev_close * 0.9
    if side == "long" and open_price >= limit_up * 0.995:
        return True
    return False


def simulate_with_fills(
    df: pd.DataFrame,
    signals: pd.Series,
    *,
    max_hold: int = 15,
    atr_tp: float = 3.0,
    atr_sl: float = 1.5,
    slippage_pct: float = 0.0005,
    use_limit_entry: bool = False,
    limit_entry_offset_pct: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Returns trades + unfilled counters."""
    stats = {
        "total_entry_signals": 0,
        "filled": 0,
        "unfilled_limit": 0,
        "unfilled_no_volume": 0,
        "unfilled_stop_limit": 0,
    }
    rows: list[dict[str, Any]] = []
    n = len(df)
    for sig_i in range(n - 2):
        if int(signals.iloc[sig_i]) <= 0:
            continue
        stats["total_entry_signals"] += 1
        entry_idx = sig_i + 1
        if entry_idx >= n:
            break
        prev_close = float(df.iloc[entry_idx - 1]["close"])
        vol = float(df.iloc[entry_idx]["volume"])
        if vol <= 0:
            stats["unfilled_no_volume"] += 1
            continue
        entry_open = float(df.iloc[entry_idx]["open"])
        if _is_stop_limit_block(prev_close, entry_open):
            stats["unfilled_stop_limit"] += 1
            continue
        target = prev_close * (1 - limit_entry_offset_pct / 100) if use_limit_entry else entry_open
        if use_limit_entry and entry_open > target:
            stats["unfilled_limit"] += 1
            continue
        entry_price = (target if use_limit_entry else entry_open) * (1 + slippage_pct)
        atr = float(df.iloc[entry_idx].get("atr_14") or entry_price * 0.02)
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
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        stats["filled"] += 1
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
    return pd.DataFrame(rows), stats
