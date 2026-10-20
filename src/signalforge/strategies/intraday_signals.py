"""Session rules for TSE day-trade catalog strategies, evaluated on intraday bars."""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

from signalforge.strategies.base import BaseStrategy

TOKYO = "Asia/Tokyo"


def _local_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return idx.tz_convert(TOKYO)


def _clock(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _windows(params: dict) -> list[tuple[time, time]]:
    raw = params.get("windows")
    if raw:
        return [(_clock(start), _clock(end)) for start, end in raw]
    return [(_clock(str(params.get("start", "09:00"))), _clock(str(params.get("end", "10:00"))))]


def _in_window(stamp: time, windows: list[tuple[time, time]]) -> bool:
    return any(start <= stamp <= end for start, end in windows)


def opening_gap_session(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    """Gap versus the previous session's last close, on the first bar of the day."""
    min_gap = float(params.get("min_gap_pct", 0.005))
    signals = pd.Series(0, index=df.index)
    if len(df) < 2:
        return signals
    local = _local_index(df)
    dates = local.date
    prev_close: float | None = None
    seen: set = set()
    for i in range(len(df)):
        day = dates[i]
        if day not in seen:
            if prev_close not in (None, 0):
                gap = (float(df.iloc[i]["open"]) - prev_close) / prev_close
                if gap >= min_gap and float(df.iloc[i]["close"]) > float(df.iloc[i]["open"]):
                    signals.iloc[i] = 1
            seen.add(day)
        prev_close = float(df.iloc[i]["close"])
    return signals


def prior_day_level_break(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    """First break of the previous session high (long) or low (short)."""
    signals = pd.Series(0, index=df.index)
    if df.empty:
        return signals
    local = _local_index(df)
    dates = pd.Series(local.date, index=df.index)
    day_high = df["high"].groupby(dates).max()
    day_low = df["low"].groupby(dates).min()
    ordered = list(day_high.index)
    prior_high: dict = {}
    prior_low: dict = {}
    for i, day in enumerate(ordered):
        if i == 0:
            continue
        prior_high[day] = float(day_high.iloc[i - 1])
        prior_low[day] = float(day_low.iloc[i - 1])
    broke_high: set = set()
    broke_low: set = set()
    for i in range(len(df)):
        day = dates.iloc[i]
        hi = prior_high.get(day)
        lo = prior_low.get(day)
        close = float(df.iloc[i]["close"])
        if hi is not None and day not in broke_high and close > hi:
            signals.iloc[i] = 1
            broke_high.add(day)
        elif lo is not None and day not in broke_low and close < lo:
            signals.iloc[i] = -1
            broke_low.add(day)
    return signals


def session_high_break(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    """Break a finished session range later the same day, with a volume filter."""
    session = str(params.get("session", "morning"))
    vr_min = float(params.get("volume_ratio_min", 1.5))
    if session == "afternoon":
        range_window = (_clock("12:30"), _clock("13:30"))
        trigger_window = (_clock("13:30"), _clock("15:00"))
    else:
        range_window = (_clock("09:00"), _clock("11:30"))
        trigger_window = (_clock("12:30"), _clock("15:00"))
    signals = pd.Series(0, index=df.index)
    local = _local_index(df)
    dates = local.date
    times = local.time
    for day in pd.unique(dates):
        pos = np.flatnonzero(dates == day)
        if len(pos) < 3:
            continue
        range_high = None
        for i in pos:
            stamp = times[i]
            if range_window[0] <= stamp <= range_window[1]:
                high = float(df.iloc[i]["high"])
                range_high = high if range_high is None else max(range_high, high)
        if range_high is None:
            continue
        for i in pos:
            stamp = times[i]
            if not (trigger_window[0] <= stamp <= trigger_window[1]):
                continue
            if stamp <= range_window[1]:
                continue
            row = df.iloc[i]
            vol = float(row["volume_ratio_20"]) if "volume_ratio_20" in df.columns else 1.0
            if vol != vol:
                vol = 0.0
            if float(row["close"]) > range_high and vol >= vr_min:
                signals.iloc[i] = 1
                break
    return signals


def session_momentum(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    """Close above the short EMA and the previous close, only inside the given clock windows."""
    ema_col = str(params.get("ema_col", "ema9"))
    windows = _windows(params)
    signals = pd.Series(0, index=df.index)
    if ema_col not in df.columns or len(df) < 2:
        return signals
    local = _local_index(df)
    times = local.time
    for i in range(1, len(df)):
        if not _in_window(times[i], windows):
            continue
        row, prev = df.iloc[i], df.iloc[i - 1]
        ema = float(row[ema_col])
        if ema == ema and float(row["close"]) > ema and float(row["close"]) > float(prev["close"]):
            signals.iloc[i] = 1
    return signals


def session_vwap_fade(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    """Fade an extension away from session VWAP inside a clock window (default: into the lunch break)."""
    windows = _windows({**{"start": "11:00", "end": "11:30"}, **params})
    col = "vwap" if "vwap" in df.columns else None
    signals = pd.Series(0, index=df.index)
    if col is None or len(df) < 2:
        return signals
    local = _local_index(df)
    times = local.time
    for i in range(1, len(df)):
        if not _in_window(times[i], windows):
            continue
        row, prev = df.iloc[i], df.iloc[i - 1]
        vwap = float(row[col])
        if vwap != vwap:
            continue
        close = float(row["close"])
        prev_close = float(prev["close"])
        if close > vwap and close < prev_close:
            signals.iloc[i] = -1
        elif close < vwap and close > prev_close:
            signals.iloc[i] = 1
    return signals


def pivot_bounce(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    """Long when price tags the prior day's pivot and closes back above it."""
    signals = pd.Series(0, index=df.index)
    if df.empty:
        return signals
    local = _local_index(df)
    dates = pd.Series(local.date, index=df.index)
    grouped = df.groupby(dates)
    day_high = grouped["high"].max()
    day_low = grouped["low"].min()
    day_close = grouped["close"].last()
    ordered = list(day_high.index)
    pivot_of: dict = {}
    for i, day in enumerate(ordered):
        if i == 0:
            continue
        prev = ordered[i - 1]
        pivot_of[day] = (float(day_high.loc[prev]) + float(day_low.loc[prev]) + float(day_close.loc[prev])) / 3.0
    used: set = set()
    for i in range(len(df)):
        day = dates.iloc[i]
        pivot = pivot_of.get(day)
        if pivot is None or day in used:
            continue
        row = df.iloc[i]
        if float(row["low"]) <= pivot and float(row["close"]) > pivot:
            signals.iloc[i] = 1
            used.add(day)
    return signals


def _parabolic_sar(high: pd.Series, low: pd.Series, af0: float = 0.02, af_step: float = 0.02, af_max: float = 0.2) -> pd.Series:
    n = len(high)
    sar = np.zeros(n)
    bull = True
    af = af0
    ep = float(high.iloc[0])
    sar[0] = float(low.iloc[0])
    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    for i in range(1, n):
        sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
        if bull:
            sar[i] = min(sar[i], l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < sar[i]:
                bull = False
                sar[i] = ep
                ep = l[i]
                af = af0
            elif h[i] > ep:
                ep = h[i]
                af = min(af + af_step, af_max)
        else:
            sar[i] = max(sar[i], h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar[i]:
                bull = True
                sar[i] = ep
                ep = h[i]
                af = af0
            elif l[i] < ep:
                ep = l[i]
                af = min(af + af_step, af_max)
    return pd.Series(sar, index=high.index)


def psar_flip(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    """Long when parabolic SAR flips from above price to below price."""
    signals = pd.Series(0, index=df.index)
    if len(df) < 3:
        return signals
    sar = _parabolic_sar(df["high"], df["low"])
    close = df["close"].to_numpy(dtype=float)
    sar_v = sar.to_numpy(dtype=float)
    for i in range(2, len(df)):
        if close[i - 1] < sar_v[i - 1] and close[i] > sar_v[i]:
            signals.iloc[i] = 1
    return signals
