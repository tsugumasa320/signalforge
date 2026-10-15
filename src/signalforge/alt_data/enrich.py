"""Merge alt-data columns into OHLCV+indicator frames before signal generation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from signalforge.alt_data.credit_balance import load_margin_frame
from signalforge.alt_data.deps import data_deps_for_strategy
from signalforge.alt_data.earnings import load_earnings
from signalforge.alt_data.sector_index import load_sector_index
from signalforge.universe.tse_listing import listing_by_ticker


def _days_since_last_event(index: pd.DatetimeIndex, event_dates: list[str]) -> pd.Series:
    if not event_dates:
        return pd.Series(np.nan, index=index)
    events = sorted(pd.Timestamp(d) for d in event_dates)
    out = []
    for ts in index:
        t = pd.Timestamp(ts).normalize()
        past = [e for e in events if e.normalize() <= t]
        if not past:
            out.append(np.nan)
        else:
            out.append((t - past[-1]).days)
    return pd.Series(out, index=index, dtype=float)


def enrich_dataframe(df: pd.DataFrame, ticker: str, strategy_id: str) -> pd.DataFrame:
    deps = data_deps_for_strategy(strategy_id)
    if not deps:
        return df
    out = df.copy()
    listing = listing_by_ticker().get(ticker) or {}

    if "sector_index" in deps:
        sector = listing.get("sector_tse")
        sec = load_sector_index(str(sector)) if sector else None
        if sec is not None and not sec.empty:
            aligned = sec.reindex(out.index, method="ffill")
            out["sector_index_close"] = aligned.astype(float)
            stock_ret = out["close"].astype(float).pct_change()
            sec_ret = out["sector_index_close"].pct_change()
            for lb in (5, 20, 60):
                out[f"sector_rs_{lb}d"] = (
                    stock_ret.rolling(lb).sum() - sec_ret.rolling(lb).sum()
                ) * 100.0
            log_spread = np.log(out["close"].astype(float) / out["sector_index_close"].astype(float))
            out["sector_log_spread"] = log_spread
            out["sector_spread_z20"] = (
                log_spread - log_spread.rolling(20).mean()
            ) / log_spread.rolling(20).std().replace(0, np.nan)

    if "earnings" in deps:
        dates = load_earnings(ticker)
        out["days_since_earnings"] = _days_since_last_event(out.index, dates)

    if "credit_balance" in deps:
        mdf = load_margin_frame(ticker)
        if mdf is not None and not mdf.empty:
            aligned = mdf.reindex(out.index, method="ffill")
            for col in ("margin_long_vol", "margin_shrt_vol", "margin_shrt_ratio"):
                if col in aligned.columns:
                    out[col] = aligned[col].astype(float)
            if "margin_shrt_ratio" in out.columns:
                out["margin_shrt_ratio_chg_4w"] = (
                    out["margin_shrt_ratio"] - out["margin_shrt_ratio"].shift(20)
                )

    return out


def maybe_enrich(df: pd.DataFrame, ticker: str, strategy_id: str) -> pd.DataFrame:
    try:
        return enrich_dataframe(df, ticker, strategy_id)
    except Exception:
        return df
