from __future__ import annotations

import pandas as pd


def earnings_dates() -> list[pd.Timestamp]:
    """Per-ticker earnings live in alt-data; no global US calendar."""
    return []


def is_earnings_blackout(
    ts: pd.Timestamp,
    blackout_days: int = 2,
) -> bool:
    if blackout_days <= 0 or not earnings_dates():
        return False
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
    """Placeholder when ML features run without per-ticker earnings cache."""
    _ = ts
    return 999


def filter_blackout_signals(
    df: pd.DataFrame,
    signal_col: str = "signal",
    blackout_days: int = 2,
) -> pd.Series:
    mask = df.index.map(lambda t: not is_earnings_blackout(t, blackout_days))
    return df[signal_col].where(mask, 0)
