"""Benchmark series for report overlays (Nikkei 225 proxy)."""

from __future__ import annotations

import pandas as pd

from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher

# 日経225連動ETF（東証上場・日足キャッシュと整合）
NIKKEI225_ETF = "1321.T"


def load_nikkei225_close(*, refresh: bool = False) -> pd.Series:
    fetcher = MarketDataFetcher(data_source="yfinance")
    cache = ParquetCache()
    df = cache.load_or_fetch(NIKKEI225_ETF, "1d", fetcher, refresh=refresh)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    s = df["close"].astype(float).sort_index()
    if s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    else:
        s.index = s.index.tz_convert("UTC")
    return s


def normalize_to_index100(series: pd.Series, start: pd.Timestamp) -> pd.Series:
    """Rebase to 100 at first available date on/after start."""
    if series.empty:
        return series
    start = pd.Timestamp(start)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    sub = series.loc[series.index >= start.normalize()]
    if sub.empty:
        sub = series
    base = float(sub.iloc[0])
    if base <= 0:
        return sub * 0.0
    return (sub / base) * 100.0


def align_benchmark_to_equity(
    equity: pd.Series,
    benchmark_close: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Return (equity_index100, benchmark_index100) on shared daily index."""
    if equity.empty:
        return equity, pd.Series(dtype=float)
    start = equity.index.min()
    eq_idx = normalize_to_index100(equity, start)
    bm = benchmark_close.reindex(equity.index).ffill()
    bm_idx = normalize_to_index100(bm.dropna(), start)
    bm_idx = bm_idx.reindex(equity.index).ffill()
    return eq_idx, bm_idx
