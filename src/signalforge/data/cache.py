from __future__ import annotations

from pathlib import Path

import pandas as pd

from signalforge.config import data_dir


class ParquetCache:
    """Local OHLCV cache (pickle primary; legacy parquet auto-migrated on read)."""

    def __init__(self, base: Path | None = None) -> None:
        self.base = base or data_dir()
        self.base.mkdir(parents=True, exist_ok=True)

    def path(self, ticker: str, timeframe: str) -> Path:
        safe = ticker.replace("/", "_")
        return self.base / f"{safe}_{timeframe}.pkl"

    def _legacy_parquet_path(self, ticker: str, timeframe: str) -> Path:
        return self.path(ticker, timeframe).with_suffix(".parquet")

    def save(self, ticker: str, timeframe: str, df: pd.DataFrame) -> Path:
        p = self.path(ticker, timeframe)
        df.to_pickle(p)
        return p

    def load(self, ticker: str, timeframe: str) -> pd.DataFrame | None:
        p = self.path(ticker, timeframe)
        if p.exists():
            df = pd.read_pickle(p)
            df.index = pd.to_datetime(df.index)
            return df

        legacy = self._legacy_parquet_path(ticker, timeframe)
        if legacy.exists():
            df = pd.read_parquet(legacy)
            df.index = pd.to_datetime(df.index)
            self.save(ticker, timeframe, df)
            return df

        return None

    def load_or_fetch(
        self,
        ticker: str,
        timeframe: str,
        fetcher,
        refresh: bool = False,
    ) -> pd.DataFrame:
        if not refresh:
            cached = self.load(ticker, timeframe)
            if cached is not None and len(cached) > 0:
                return cached
        df = fetcher.fetch(ticker, timeframe)  # type: ignore[arg-type]
        self.save(ticker, timeframe, df)
        return df
