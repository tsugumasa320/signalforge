"""Daily signal counts for Izanami-style bar chart."""

from __future__ import annotations

import pandas as pd


def daily_signal_bars(trades: pd.DataFrame) -> list[dict]:
    if trades.empty:
        return []
    t = trades.copy()
    t["signal_date"] = pd.to_datetime(t["signal_time"]).dt.date
    rows = []
    for d, grp in t.groupby("signal_date"):
        pnl = grp["pnl_pct"].astype(float)
        rows.append(
            {
                "date": str(d),
                "count": len(grp),
                "avg_pnl_pct": float(pnl.mean()),
                "positive": float(pnl.mean()) >= 0,
            }
        )
    return sorted(rows, key=lambda x: x["date"])
