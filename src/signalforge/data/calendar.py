from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd


# Approximate NVDA earnings dates (extend as needed)
NVDA_EARNINGS = [
    "2023-02-22",
    "2023-05-24",
    "2023-08-23",
    "2023-11-21",
    "2024-02-21",
    "2024-05-22",
    "2024-08-28",
    "2024-11-20",
    "2025-02-26",
    "2025-05-28",
    "2025-08-27",
]


def earnings_dates() -> list[pd.Timestamp]:
    return [pd.Timestamp(d) for d in NVDA_EARNINGS]


def is_earnings_blackout(
    ts: pd.Timestamp,
    blackout_days: int = 2,
) -> bool:
    ts = pd.Timestamp(ts)
    if ts.tz is not None:
        ts = ts.tz_localize(None)
    ts = ts.normalize()
    for ed in earnings_dates():
        ed_naive = ed.tz_localize(None) if ed.tz is not None else ed
        if abs((ts - ed_naive).days) <= blackout_days:
            return True
    return False


def days_to_next_earnings(ts: pd.Timestamp) -> int:
    ts = pd.Timestamp(ts)
    if ts.tz is not None:
        ts = ts.tz_localize(None)
    ts = ts.normalize()
    future = []
    for ed in earnings_dates():
        ed_naive = ed.tz_localize(None) if ed.tz is not None else ed
        if ed_naive >= ts:
            future.append(ed_naive)
    if not future:
        return 999
    return (min(future) - ts).days


def filter_blackout_signals(
    df: pd.DataFrame,
    signal_col: str = "signal",
    blackout_days: int = 2,
) -> pd.Series:
    mask = df.index.map(lambda t: not is_earnings_blackout(t, blackout_days))
    return df[signal_col].where(mask, 0)
