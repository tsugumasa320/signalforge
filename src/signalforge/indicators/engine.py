from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    line = ema_fast - ema_slow
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    mid = close.rolling(period).mean()
    dev = close.rolling(period).std()
    upper = mid + std * dev
    lower = mid - std * dev
    width = (upper - lower) / mid
    return upper, mid, lower, width


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    atr_val = atr(high, low, close, period)
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr_val)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr_val)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.rolling(period).mean()


def daily_vwap(df: pd.DataFrame, timezone: str = "America/New_York") -> pd.Series:
    """Intraday VWAP resetting each trading day."""
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    local_dates = idx.tz_convert(timezone).date
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    vwap = pd.Series(index=df.index, dtype=float)
    for d in pd.unique(local_dates):
        mask = local_dates == d
        sub_pv = pv.loc[mask].cumsum()
        sub_v = df.loc[mask, "volume"].cumsum()
        vwap.loc[mask] = sub_pv / sub_v.replace(0, np.nan)
    return vwap


class IndicatorEngine:
    """Compute technical indicators with shift(1) for look-ahead safety."""

    def __init__(self, timezone: str = "America/New_York", shift: int = 1) -> None:
        self.timezone = timezone
        self.shift = shift

    def compute(self, df: pd.DataFrame, intraday: bool = False) -> pd.DataFrame:
        out = df.copy()
        c, h, l, v = out["close"], out["high"], out["low"], out["volume"]

        out["ema9"] = ema(c, 9)
        out["ema20"] = ema(c, 20)
        out["ema21"] = ema(c, 21)
        out["ema50"] = ema(c, 50)
        out["ema200"] = ema(c, 200)
        out["rsi_14"] = rsi(c, 14)
        macd_line, macd_sig, macd_hist = macd(c)
        out["macd"] = macd_line
        out["macd_signal"] = macd_sig
        out["macd_histogram"] = macd_hist
        bb_u, bb_m, bb_l, bb_w = bollinger(c)
        out["bb_upper"] = bb_u
        out["bb_mid"] = bb_m
        out["bb_lower"] = bb_l
        out["bb_width"] = bb_w
        out["atr_14"] = atr(h, l, c, 14)
        out["atr_pct"] = out["atr_14"] / c
        out["adx_14"] = adx(h, l, c, 14)
        out["volume_ma20"] = v.rolling(20).mean()
        out["volume_ratio_20"] = v / out["volume_ma20"]
        out["ema20_distance_pct"] = (c - out["ema20"]) / out["ema20"]

        if intraday:
            out["vwap"] = daily_vwap(out, self.timezone)

        if self.shift:
            indicator_cols = [
                col
                for col in out.columns
                if col not in ("open", "high", "low", "close", "volume")
            ]
            out[indicator_cols] = out[indicator_cols].shift(self.shift)

        return out

    def bb_width_percentile(self, df: pd.DataFrame, window: int = 252) -> pd.Series:
        return df["bb_width"].rolling(window, min_periods=20).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100,
            raw=False,
        )
