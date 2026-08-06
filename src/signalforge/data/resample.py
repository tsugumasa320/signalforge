from __future__ import annotations

import pandas as pd


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample OHLCV to a coarser timeframe."""
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    cols = [c for c in agg if c in df.columns]
    return df[cols].resample(rule).agg({c: agg[c] for c in cols}).dropna()
