"""Entry-time features for ranking / filtering pooled trades (no look-ahead)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from signalforge.data.cache import ParquetCache

REGIME_BENCHMARK = "1321.T"


def _naive_dates(values: pd.Series | pd.Index) -> pd.Series:
    ts = pd.to_datetime(pd.Series(values), utc=True)
    return ts.dt.tz_localize(None).dt.normalize()


@lru_cache(maxsize=8192)
def _close_series(ticker: str) -> pd.Series | None:
    df = ParquetCache().load(ticker, "1d")
    if df is None or df.empty or "close" not in df.columns:
        return None
    s = df["close"].astype(float)
    s.index = _naive_dates(s.index).values
    return s[~s.index.duplicated(keep="last")].sort_index()


@lru_cache(maxsize=8192)
def _turnover_series(ticker: str, window: int) -> pd.Series | None:
    df = ParquetCache().load(ticker, "1d")
    if df is None or df.empty or not {"close", "volume"} <= set(df.columns):
        return None
    tv = (df["close"].astype(float) * df["volume"].astype(float)).rolling(window, min_periods=max(5, window // 2)).mean()
    tv.index = _naive_dates(tv.index).values
    return tv[~tv.index.duplicated(keep="last")].sort_index()


def liquid_tickers(
    min_median_turnover_jpy: float = 3e8,
    *,
    since: str | None = None,
    lookback_bars: int | None = None,
) -> list[str]:
    """TSE listing tickers whose median 20-day trading value (since / last N bars) clears the floor."""
    from signalforge.universe.tse_listing import listing_by_ticker

    out: list[str] = []
    for sym in sorted(listing_by_ticker()):
        tv = _turnover_series(sym, 20)
        if tv is None or tv.empty:
            continue
        if since:
            tv = tv[tv.index >= np.datetime64(since)]
        if lookback_bars:
            tv = tv.iloc[-lookback_bars:]
        tv = tv.dropna()
        if len(tv) and float(np.median(tv.values)) >= min_median_turnover_jpy:
            out.append(sym)
    return out


def attach_turnover(pool: pd.DataFrame, *, window: int = 20) -> pd.DataFrame:
    """turnover_jpy = mean daily trading value (close × volume) over `window` bars before entry."""
    out = pool.copy()
    out["turnover_jpy"] = np.nan
    if out.empty or "ticker" not in out.columns:
        return out
    entry = _naive_dates(out["entry_time"]).values
    for ticker, idx in out.groupby("ticker").groups.items():
        tv = _turnover_series(str(ticker), window)
        if tv is None or tv.empty:
            continue
        pos = np.searchsorted(tv.index.values, entry[idx], side="left") - 1
        out.loc[idx, "turnover_jpy"] = np.where(pos >= 0, tv.values[np.clip(pos, 0, None)], np.nan)
    return out


def attach_kairi(pool: pd.DataFrame, *, ma_window: int = 25) -> pd.DataFrame:
    """kairi_pct = close / SMA(ma_window) - 1 on the last bar strictly before entry (signal bar)."""
    out = pool.copy()
    out["kairi_pct"] = np.nan
    if out.empty or "ticker" not in out.columns:
        return out
    entry = _naive_dates(out["entry_time"]).values
    for ticker, idx in out.groupby("ticker").groups.items():
        close = _close_series(str(ticker))
        if close is None or len(close) < ma_window:
            continue
        kairi = (close / close.rolling(ma_window).mean() - 1.0) * 100.0
        pos = np.searchsorted(kairi.index.values, entry[idx], side="left") - 1
        vals = np.where(pos >= 0, kairi.values[np.clip(pos, 0, None)], np.nan)
        out.loc[idx, "kairi_pct"] = vals
    return out


def attach_volatility(pool: pd.DataFrame, *, window: int = 20) -> pd.DataFrame:
    """vol_pct = stdev of daily returns over `window` bars, on the last bar before entry."""
    out = pool.copy()
    out["vol_pct"] = np.nan
    if out.empty or "ticker" not in out.columns:
        return out
    entry = _naive_dates(out["entry_time"]).values
    for ticker, idx in out.groupby("ticker").groups.items():
        close = _close_series(str(ticker))
        if close is None or len(close) < window + 1:
            continue
        vol = close.pct_change().rolling(window).std() * 100.0
        pos = np.searchsorted(vol.index.values, entry[idx], side="left") - 1
        out.loc[idx, "vol_pct"] = np.where(pos >= 0, vol.values[np.clip(pos, 0, None)], np.nan)
    return out


def attach_ticker_history(pool: pd.DataFrame, *, min_prior_trades: int = 3) -> pd.DataFrame:
    """hist_mean_pnl = mean pnl_pct of the same ticker's trades that exited before this entry."""
    out = pool.copy()
    out["hist_n"] = 0
    out["hist_mean_pnl"] = np.nan
    if out.empty or "ticker" not in out.columns:
        return out
    entry = _naive_dates(out["entry_time"]).values
    exit_ = _naive_dates(out["exit_time"]).values
    pnl = out["pnl_pct"].astype(float).values
    hist_n = np.zeros(len(out), dtype=int)
    hist_mean = np.full(len(out), np.nan)
    for _, idx in out.groupby("ticker").indices.items():
        order = idx[np.argsort(exit_[idx], kind="stable")]
        ex_sorted = exit_[order]
        cum = np.concatenate([[0.0], np.cumsum(pnl[order])])
        n = np.searchsorted(ex_sorted, entry[idx], side="left")
        hist_n[idx] = n
        with np.errstate(invalid="ignore", divide="ignore"):
            hist_mean[idx] = np.where(n >= min_prior_trades, cum[n] / np.maximum(n, 1), np.nan)
    out["hist_n"] = hist_n
    out["hist_mean_pnl"] = hist_mean
    return out


def attach_breadth(pool: pd.DataFrame, *, window: int = 250, min_history: int = 60) -> pd.DataFrame:
    """
    breadth_n = number of pooled signals with the same entry day (all known at the prior close).
    breadth_rank = share of the previous `window` entry days with strictly fewer signals (0..1).
    """
    out = pool.copy()
    if out.empty:
        out["breadth_n"] = 0
        out["breadth_rank"] = np.nan
        return out
    day = _naive_dates(out["entry_time"])
    counts = day.value_counts().sort_index()
    vals = counts.values.astype(float)
    ranks = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        lo = max(0, i - window)
        hist = vals[lo:i]
        if len(hist) >= min_history:
            ranks[i] = float((hist < vals[i]).mean())
    rank_map = pd.Series(ranks, index=counts.index)
    out["breadth_n"] = day.map(counts).values
    out["breadth_rank"] = day.map(rank_map).values
    return out


@lru_cache(maxsize=4)
def regime_table(benchmark: str = REGIME_BENCHMARK) -> pd.DataFrame:
    """Per-day benchmark state, already shifted so each row only uses the previous close."""
    close = _close_series(benchmark)
    if close is None:
        return pd.DataFrame(columns=["above_ma200", "ret5_pct"])
    tbl = pd.DataFrame(
        {
            "above_ma200": close > close.rolling(200).mean(),
            "ret5_pct": (close / close.shift(5) - 1.0) * 100.0,
        }
    )
    return tbl.shift(1)


def attach_regime(pool: pd.DataFrame, *, benchmark: str = REGIME_BENCHMARK) -> pd.DataFrame:
    out = pool.copy()
    tbl = regime_table(benchmark)
    if out.empty or tbl.empty:
        out["mkt_above_ma200"] = True
        out["mkt_ret5_pct"] = 0.0
        return out
    entry = _naive_dates(out["entry_time"]).values
    pos = np.searchsorted(tbl.index.values, entry, side="right") - 1
    valid = pos >= 0
    safe = np.clip(pos, 0, None)
    above = tbl["above_ma200"].astype("float").values[safe]
    ret5 = tbl["ret5_pct"].values[safe]
    out["mkt_above_ma200"] = np.where(valid & ~np.isnan(above), above == 1.0, True)
    out["mkt_ret5_pct"] = np.where(valid, ret5, np.nan)
    return out
