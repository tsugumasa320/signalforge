from __future__ import annotations

from typing import Any

import pandas as pd


def resolve_backtest_dates(cfg: dict[str, Any]) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Return (start, end) timestamps for the evaluation window."""
    bt = cfg.get("backtest", {})
    nvda = cfg.get("_nvda", {})
    defaults = cfg.get("_defaults", {})

    start_raw = bt.get("start_date") or nvda.get("backtest_start_date") or defaults.get("backtest_start_date")
    end_raw = bt.get("end_date") or nvda.get("backtest_end_date") or defaults.get("backtest_end_date")

    start = pd.Timestamp(start_raw) if start_raw else None
    end = pd.Timestamp(end_raw) if end_raw else None
    return start, end


def _align_tz(ts: pd.Timestamp, index: pd.DatetimeIndex) -> pd.Timestamp:
    if index.tz is not None:
        if ts.tzinfo is None:
            return ts.tz_localize(index.tz)
        return ts.tz_convert(index.tz)
    if ts.tzinfo is not None:
        return ts.tz_convert(None)
    return ts


def slice_for_indicators(df: pd.DataFrame, start: pd.Timestamp | None, warmup_calendar_days: int = 400) -> pd.DataFrame:
    """Keep enough history before start_date so EMA200/ADX etc. are valid at window open."""
    if df.empty or start is None:
        return df
    start = _align_tz(start, df.index)
    warmup_from = start - pd.Timedelta(days=warmup_calendar_days)
    return df[df.index >= warmup_from]


def trim_to_backtest_window(
    df: pd.DataFrame,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> pd.DataFrame:
    if df.empty:
        return df
    out = df
    if start is not None:
        start = _align_tz(start, df.index)
        out = out[out.index >= start]
    if end is not None:
        end = _align_tz(end, df.index)
        out = out[out.index <= end]
    return out


def window_label(start: pd.Timestamp | None, end: pd.Timestamp | None, n_bars: int) -> str:
    if start is None and end is None:
        return f"全期間 ({n_bars} bars)"
    s = start.strftime("%Y-%m-%d") if start is not None else "—"
    e = end.strftime("%Y-%m-%d") if end is not None else "最新"
    return f"{s} 〜 {e} ({n_bars} bars)"
