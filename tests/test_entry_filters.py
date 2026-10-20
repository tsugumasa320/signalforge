"""Daily mean-reversion entries skip earnings and require an hourly oversold print."""

from __future__ import annotations

import pandas as pd

from signalforge.data.entry_filters import (
    apply_earnings_blackout,
    apply_hourly_confirmation,
    session_rsi_extremes,
    uses_reversion_entry,
)


def test_earnings_blackout_covers_the_day_before_and_after():
    idx = pd.to_datetime(["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09"])
    signals = pd.Series([1, 1, 1, 1], index=idx)
    out = apply_earnings_blackout(signals, ["2026-11-05"], days=1)
    assert list(out.astype(int)) == [0, 0, 0, 1]


def _session_hours(days: list[str]) -> pd.DatetimeIndex:
    stamps = []
    for day in days:
        for hour in range(9, 16):
            stamps.append(pd.Timestamp(f"{day} {hour:02d}:00", tz="Asia/Tokyo"))
    return pd.DatetimeIndex(stamps)


def test_hourly_confirmation_keeps_a_day_that_sold_off():
    days = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"]
    hours = _session_hours(days)
    close = [100.0] * (len(hours) - 7) + [90, 80, 70, 60, 50, 40, 30]
    hourly = pd.DataFrame({"close": close}, index=hours)
    extremes = session_rsi_extremes(hourly)
    day = hours[-1].date()
    assert extremes[day][0] <= 30

    daily_idx = pd.to_datetime([str(day), "2026-09-01"])
    signals = pd.Series([1, 1], index=daily_idx)
    out = apply_hourly_confirmation(signals, extremes)
    assert int(out.iloc[0]) == 1
    assert int(out.iloc[1]) == 1


def test_hourly_confirmation_drops_a_day_that_never_got_oversold():
    days = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]
    hours = _session_hours(days)
    close = []
    price = 100.0
    for i in range(len(hours)):
        price += 0.4 if i % 2 == 0 else -0.2
        close.append(price)
    hourly = pd.DataFrame({"close": close}, index=hours)
    extremes = session_rsi_extremes(hourly)
    day = hours[-1].date()
    assert extremes[day][0] > 30
    signals = pd.Series([1], index=pd.to_datetime([str(day)]))
    out = apply_hourly_confirmation(signals, extremes)
    assert int(out.iloc[0]) == 0


def test_reversion_templates_are_the_only_ones_filtered():
    assert uses_reversion_entry("mean_reversion_short_term")
    assert uses_reversion_entry("bb_lower_rsi_oversold")
    assert uses_reversion_entry("cci_zero_cross")
    assert uses_reversion_entry("rsi_dip_200ma")
    assert not uses_reversion_entry("bb_upper_rsi_exit")
    assert not uses_reversion_entry("ichimoku_tk_cross")
    assert not uses_reversion_entry("trailing_atr_chandelier")
    assert not uses_reversion_entry("earnings_drift")
    assert not uses_reversion_entry("low_pbr_value_reversal")
