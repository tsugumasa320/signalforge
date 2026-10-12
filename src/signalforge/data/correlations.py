from __future__ import annotations

from typing import Any

import pandas as pd

from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.data.window import slice_for_indicators, trim_to_backtest_window
from signalforge.indicators.engine import IndicatorEngine


def load_benchmark_pair(
    cache: ParquetCache,
    fetcher: MarketDataFetcher,
    correlation_tickers: list[str],
    timeframe: str,
    *,
    refresh: bool,
    engine_ind: IndicatorEngine,
    intraday: bool,
    bt_start: pd.Timestamp | None,
    bt_end: pd.Timestamp | None,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """First two correlation symbols map to ML features (index / sector RS slots)."""
    frames: list[pd.DataFrame | None] = [None, None]
    for i, sym in enumerate(correlation_tickers[:2]):
        try:
            cdf = cache.load_or_fetch(sym, timeframe, fetcher, refresh=refresh)
        except Exception:
            cdf = cache.load_or_fetch(sym, timeframe, MarketDataFetcher("yfinance"), refresh=refresh)
        cdf = slice_for_indicators(cdf, bt_start)
        cdf = engine_ind.compute(cdf, intraday=intraday)
        cdf = trim_to_backtest_window(cdf, bt_start, bt_end)
        frames[i] = cdf
    return frames[0], frames[1]
