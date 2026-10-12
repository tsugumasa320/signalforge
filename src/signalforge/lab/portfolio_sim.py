"""Capital-constrained portfolio simulation (Izanami 最適分散投資 approximation)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def simulate_diversified_portfolio(
    trades: pd.DataFrame,
    *,
    initial_capital: float = 1_000_000.0,
    max_positions: int = 5,
    position_pct: float | None = None,
) -> dict[str, Any]:
    """
    Greedy non-overlapping: earliest entry first, skip if slot full until exit frees capital.
    Each trade uses fixed notional fraction of *current* equity at entry.
    """
    if trades.empty:
        return {"final_equity": initial_capital, "total_return_pct": 0.0, "accepted_trades": 0, "skipped": 0}

    t = trades.sort_values("entry_time").copy()
    t["entry_ts"] = pd.to_datetime(t["entry_time"])
    t["exit_ts"] = pd.to_datetime(t["exit_time"])
    cash = initial_capital
    open_slots: list[dict] = []
    accepted: list[dict] = []
    skipped = 0
    pct = position_pct if position_pct is not None else min(1.0 / max(max_positions, 1), 0.2)

    for _, row in t.iterrows():
        open_slots = [s for s in open_slots if s["exit_ts"] > row["entry_ts"]]
        if len(open_slots) >= max_positions:
            skipped += 1
            continue
        notional = cash * pct
        if notional <= 0:
            skipped += 1
            continue
        pnl_frac = float(row["pnl_pct"]) / 100.0
        cash += notional * pnl_frac
        open_slots.append({"exit_ts": row["exit_ts"]})
        accepted.append({**row.to_dict(), "notional": notional, "pnl_jpy": notional * pnl_frac})

    ret = (cash / initial_capital - 1) * 100 if initial_capital else 0.0
    return {
        "initial_capital": initial_capital,
        "final_equity": cash,
        "total_return_pct": ret,
        "accepted_trades": len(accepted),
        "skipped_overlap": skipped,
        "max_positions": max_positions,
        "position_pct": pct,
    }
