"""Equal-weight sector indices from cached OHLCV (TSE33 業種)."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from signalforge.alt_data.paths import sector_index_meta_path, sector_index_path
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.universe.tse_listing import listing_by_ticker, list_tse_tickers


def tickers_by_sector() -> dict[str, list[str]]:
    listing = listing_by_ticker()
    out: dict[str, list[str]] = {}
    for sym in list_tse_tickers():
        meta = listing.get(sym) or {}
        sec = meta.get("sector_tse")
        if not sec or sec == "ETF":
            continue
        out.setdefault(str(sec), []).append(sym)
    return out


def build_sector_index_series(
    sector_tse: str,
    tickers: list[str],
    *,
    timeframe: str = "1d",
    refresh: bool = False,
    min_members: int = 5,
) -> pd.Series | None:
    if len(tickers) < min_members:
        return None
    cache = ParquetCache()
    fetcher = MarketDataFetcher("yfinance")
    closes: list[pd.Series] = []
    for sym in tickers:
        try:
            df = cache.load_or_fetch(sym, timeframe, fetcher, refresh=refresh)
        except Exception:
            continue
        if df.empty or "close" not in df.columns:
            continue
        s = df["close"].astype(float)
        s.index = pd.to_datetime(s.index)
        closes.append(s.rename(sym))
    if len(closes) < min_members:
        return None
    panel = pd.concat(closes, axis=1).sort_index().ffill()
    rets = panel.pct_change()
    ew = rets.mean(axis=1, skipna=True)
    index = (1.0 + ew.fillna(0.0)).cumprod() * 100.0
    index.name = "close"
    return index


def save_sector_index(sector_tse: str, series: pd.Series) -> Path:
    path = sector_index_path(sector_tse)
    series.to_frame().to_parquet(path)
    meta_path = sector_index_meta_path()
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    meta[path.name] = {"sector_tse": sector_tse, "n_bars": int(len(series))}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_sector_index(sector_tse: str) -> pd.Series | None:
    path = sector_index_path(sector_tse)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if df.empty:
        return None
    col = "close" if "close" in df.columns else df.columns[0]
    s = df[col].astype(float)
    s.index = pd.to_datetime(s.index)
    return s


def build_all_sector_indices(*, refresh: bool = False, progress_cb=None) -> dict[str, int]:
    groups = tickers_by_sector()
    built = 0
    for i, (sector, tickers) in enumerate(sorted(groups.items()), start=1):
        if progress_cb:
            progress_cb(i, len(groups), sector)
        series = build_sector_index_series(sector, tickers, refresh=refresh)
        if series is not None and len(series) > 20:
            save_sector_index(sector, series)
            built += 1
    return {"sectors_total": len(groups), "sectors_built": built}
