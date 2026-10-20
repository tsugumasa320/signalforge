"""Entry filters for daily mean-reversion, using only current Yahoo data.

Earnings dates are the announcement calendar (no 12-week vendor delay).
Hourly bars cover about the last two years. Days without an hourly cache
keep the daily signal.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from signalforge.alt_data.earnings import load_earnings
from signalforge.config import load_implementation_map
from signalforge.data.cache import ParquetCache
from signalforge.indicators.engine import rsi

EARNINGS_BLACKOUT_DAYS = 1
HOURLY_LONG_RSI_MAX = 30.0
HOURLY_SHORT_RSI_MIN = 70.0

_REVERSION_TEMPLATES = frozenset(
    {
        "mean_reversion_rsi",
        "rsi_oversold",
        "kairi_mean_reversion",
        "cci_cross",
        "gap_fill_reversal",
    }
)

_earnings_cache: dict[str, list[str]] = {}
_hourly_cache: dict[str, dict[date, tuple[float, float]]] = {}


def session_date(ts: pd.Timestamp | datetime | str) -> date:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("Asia/Tokyo")
    return t.date()


def uses_reversion_entry(strategy_id: str) -> bool:
    """Price-fade strategies. Approximations and earnings-drift stay unchanged."""
    spec = (load_implementation_map().get("strategies") or {}).get(strategy_id) or {}
    if not isinstance(spec, dict) or spec.get("approximation"):
        return False
    if "earnings" in (spec.get("data_deps") or []):
        return False
    template = spec.get("template")
    if template == "bb_rsi":
        return str((spec.get("params") or {}).get("side", "lower")) == "lower"
    return template in _REVERSION_TEMPLATES


def apply_earnings_blackout(
    signals: pd.Series,
    earnings_dates: list[str],
    *,
    days: int = EARNINGS_BLACKOUT_DAYS,
) -> pd.Series:
    events = []
    for raw in earnings_dates:
        try:
            events.append(date.fromisoformat(str(raw)[:10]))
        except ValueError:
            continue
    if days <= 0 or not events:
        return signals
    blocked = []
    for ts in signals.index:
        bar = session_date(ts)
        blocked.append(any(abs((bar - event).days) <= days for event in events))
    return signals.mask(pd.Series(blocked, index=signals.index), 0)


def session_rsi_extremes(df: pd.DataFrame) -> dict[date, tuple[float, float]]:
    if df is None or df.empty or "close" not in df.columns:
        return {}
    work = df.sort_index()
    idx = work.index
    if idx.tz is None:
        local = idx.tz_localize("Asia/Tokyo")
    else:
        local = idx.tz_convert("Asia/Tokyo")
    mask = (local.hour >= 9) & (local.hour <= 15)
    work = work.loc[mask]
    local = local[mask]
    if work.empty:
        return {}
    values = rsi(work["close"].astype(float), 14)
    buckets: dict[date, list[float]] = {}
    for ts, val in zip(local, values, strict=False):
        if pd.isna(val):
            continue
        buckets.setdefault(ts.date(), []).append(float(val))
    return {day: (min(vals), max(vals)) for day, vals in buckets.items()}


def apply_hourly_confirmation(
    signals: pd.Series,
    extremes: dict[date, tuple[float, float]],
    *,
    long_max: float = HOURLY_LONG_RSI_MAX,
    short_min: float = HOURLY_SHORT_RSI_MIN,
) -> pd.Series:
    if not extremes:
        return signals
    days = [session_date(ts) for ts in signals.index]
    known = pd.Series([day in extremes for day in days], index=signals.index)
    lo = pd.Series(
        [extremes[day][0] if day in extremes else pd.NA for day in days],
        index=signals.index,
        dtype="Float64",
    )
    hi = pd.Series(
        [extremes[day][1] if day in extremes else pd.NA for day in days],
        index=signals.index,
        dtype="Float64",
    )
    sig = signals.astype(float)
    drop_long = ((sig > 0) & known & (lo > long_max)).fillna(False).astype(bool)
    drop_short = ((sig < 0) & known & (hi < short_min)).fillna(False).astype(bool)
    return signals.mask(drop_long | drop_short, 0)


def _earnings_for(ticker: str) -> list[str]:
    if ticker not in _earnings_cache:
        _earnings_cache[ticker] = load_earnings(ticker)
    return _earnings_cache[ticker]


def _hourly_for(ticker: str) -> dict[date, tuple[float, float]]:
    if ticker not in _hourly_cache:
        frame = ParquetCache().load(ticker, "1h")
        _hourly_cache[ticker] = session_rsi_extremes(frame) if frame is not None else {}
    return _hourly_cache[ticker]


def filter_reversion_signals(
    signals: pd.Series,
    *,
    ticker: str,
    strategy_id: str,
    timeframe: str,
) -> pd.Series:
    if timeframe != "1d" or not uses_reversion_entry(strategy_id):
        return signals
    out = apply_earnings_blackout(signals, _earnings_for(ticker))
    return apply_hourly_confirmation(out, _hourly_for(ticker))
