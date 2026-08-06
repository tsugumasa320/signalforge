from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd
import yfinance as yf

Timeframe = Literal["1d", "1h", "5m", "15m"]


class MarketDataFetcher:
    """Fetch OHLCV from yfinance (default) or Alpaca (optional)."""

    YF_INTERVAL_MAP = {
        "1d": "1d",
        "1h": "1h",
        "5m": "5m",
        "15m": "15m",
    }

    def __init__(self, data_source: str = "yfinance") -> None:
        self.data_source = data_source

    def fetch(
        self,
        ticker: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        if self.data_source == "alpaca":
            try:
                return self._fetch_alpaca(ticker, timeframe, start, end)
            except Exception:
                pass
        return self._fetch_yfinance(ticker, timeframe, start, end)

    def _fetch_yfinance(
        self,
        ticker: str,
        timeframe: Timeframe,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        interval = self.YF_INTERVAL_MAP[timeframe]
        end = end or datetime.now()
        if start is None:
            if timeframe == "1d":
                start = end - timedelta(days=365 * 20)
            elif timeframe in ("5m", "15m"):
                start = end - timedelta(days=55)
            else:
                start = end - timedelta(days=700)

        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval=interval,
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            raise ValueError(f"No data returned for {ticker} {timeframe}")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index.name = "timestamp"
        return df[["open", "high", "low", "close", "volume"]].dropna()

    def _fetch_alpaca(
        self,
        ticker: str,
        timeframe: Timeframe,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        api_key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_SECRET_KEY")
        if not api_key or not secret:
            raise ValueError("Alpaca credentials not set")

        tf_map = {
            "1d": TimeFrame(1, TimeFrameUnit.Day),
            "1h": TimeFrame(1, TimeFrameUnit.Hour),
            "5m": TimeFrame(5, TimeFrameUnit.Minute),
            "15m": TimeFrame(15, TimeFrameUnit.Minute),
        }
        end = end or datetime.now()
        if start is None:
            if timeframe in ("5m", "15m"):
                start = end - timedelta(days=365 * 2)
            else:
                start = end - timedelta(days=365 * 10)

        chunk_days = {
            "1d": 730,
            "1h": 120,
            "5m": 30,
            "15m": 45,
        }[timeframe]

        client = StockHistoricalDataClient(api_key, secret)
        frames: list[pd.DataFrame] = []
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=chunk_days), end)
            req = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=tf_map[timeframe],
                start=chunk_start,
                end=chunk_end,
            )
            bars = client.get_stock_bars(req).df
            if not bars.empty:
                frames.append(bars)
            chunk_start = chunk_end

        if not frames:
            raise ValueError(f"No Alpaca data for {ticker}")

        bars = pd.concat(frames)
        bars = bars.reset_index()
        if "symbol" in bars.columns:
            bars = bars[bars["symbol"] == ticker]
        bars = bars.drop_duplicates(subset=["timestamp"])
        bars = bars.set_index("timestamp").sort_index()
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        bars.index.name = "timestamp"
        bars = bars.rename(
            columns={
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            }
        )
        return bars[["open", "high", "low", "close", "volume"]]
