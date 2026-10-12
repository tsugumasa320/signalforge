"""Disk-backed OHLCV+indicator frames — reused across strategies (same style/ticker)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.config import data_dir, load_style_config, market_context
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.data.window import resolve_backtest_dates, slice_for_indicators, trim_to_backtest_window
from signalforge.indicators.engine import IndicatorEngine
from signalforge.pipeline import resolve_data_source

_file_lock = threading.Lock()


def _prep_path(style: str, sym: str, timeframe: str) -> Path:
    safe = sym.replace("/", "_")
    return data_dir() / "cache" / "prep" / f"{safe}_{style}_{timeframe}.pkl"


def _compute_bundle(style: str, sym: str, refresh_data: bool) -> dict[str, Any]:
    cfg = load_style_config(style)
    mc = market_context(cfg)
    timeframe = cfg.get("timeframe", "1d")
    data_source = resolve_data_source(style, cfg)
    fetcher = MarketDataFetcher(data_source=data_source)
    cache = ParquetCache()
    try:
        df = cache.load_or_fetch(sym, timeframe, fetcher, refresh=refresh_data)
    except Exception:
        if data_source == "alpaca":
            fetcher = MarketDataFetcher(data_source="yfinance")
            df = cache.load_or_fetch(sym, timeframe, fetcher, refresh=refresh_data)
        else:
            raise
    bt_start, bt_end = resolve_backtest_dates(cfg)
    df = slice_for_indicators(df, bt_start)
    intraday = style == "daytrade" or style.startswith("daytrade")
    tz = mc.get("timezone", "Asia/Tokyo")
    engine_ind = IndicatorEngine(timezone=tz)
    df = engine_ind.compute(df, intraday=intraday)
    df = trim_to_backtest_window(df, bt_start, bt_end)
    return {
        "df": df,
        "bt_start": bt_start,
        "bt_end": bt_end,
        "style": style,
        "sym": sym,
        "timeframe": timeframe,
        "data_source": data_source,
    }


def load_or_prepare_ticker(style: str, sym: str, *, refresh_data: bool = False) -> dict[str, Any]:
    """Load trimmed indicator frame from disk cache or build once per (style, ticker)."""
    cfg = load_style_config(style)
    timeframe = cfg.get("timeframe", "1d")
    path = _prep_path(style, sym, timeframe)
    if path.exists() and not refresh_data:
        bundle = pd.read_pickle(path)
        if isinstance(bundle, dict) and "df" in bundle:
            return bundle
    with _file_lock:
        if path.exists() and not refresh_data:
            bundle = pd.read_pickle(path)
            if isinstance(bundle, dict) and "df" in bundle:
                return bundle
        bundle = _compute_bundle(style, sym, refresh_data)
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(bundle, path)
        return bundle
