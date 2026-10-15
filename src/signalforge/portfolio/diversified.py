"""Shared-capital diversified simulation (1 account, max concurrent positions)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from signalforge.config import load_backtest_defaults
from signalforge.experiments.series import TRADES_COMPACT_KEY, ticker_row_has_series, unpack_trades
from signalforge.experiments.storage import load_strategy_header, load_ticker_rows
from signalforge.lab.portfolio_sim import simulate_diversified_portfolio


def default_diversified_params(
    *,
    initial_cash_jpy: float | None = None,
    max_positions: int = 5,
    position_pct: float = 0.2,
) -> dict[str, Any]:
    defaults = load_backtest_defaults()
    cap = defaults.get("capital") or {}
    initial = float(initial_cash_jpy if initial_cash_jpy is not None else cap.get("initial_cash_jpy") or 3_000_000)
    return {
        "initial_capital": initial,
        "max_positions": max_positions,
        "position_pct": position_pct,
    }


def trades_pool_from_ticker_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Merge per-ticker compact trades into one DataFrame (ticker, entry_time, exit_time, pnl_pct)."""
    frames: list[pd.DataFrame] = []
    for row in rows:
        if row.get("error"):
            continue
        compact = row.get(TRADES_COMPACT_KEY)
        if not compact:
            continue
        trades = unpack_trades(compact)
        if trades.empty:
            continue
        trades = trades.copy()
        trades["ticker"] = row.get("ticker") or row.get("symbol") or "?"
        frames.append(trades)
    if not frames:
        return pd.DataFrame()
    pool = pd.concat(frames, ignore_index=True)
    pool["entry_time"] = pd.to_datetime(pool["entry_time"])
    pool["exit_time"] = pd.to_datetime(pool["exit_time"])
    return pool.sort_values("entry_time").reset_index(drop=True)


def filter_trades_after(pool: pd.DataFrame, cutoff: pd.Timestamp | None) -> pd.DataFrame:
    if pool.empty or cutoff is None:
        return pool
    entries = pd.to_datetime(pool["entry_time"], utc=True)
    ts = pd.Timestamp(cutoff)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return pool.loc[entries > ts].reset_index(drop=True)


def simulate_from_experiment_strategy(
    strategy_id: str,
    *,
    initial_cash_jpy: float | None = None,
    max_positions: int = 5,
    position_pct: float = 0.2,
    entry_after: pd.Timestamp | None = None,
) -> dict[str, Any]:
    doc = load_strategy_header(strategy_id)
    if not doc:
        raise FileNotFoundError(f"実験 JSON がありません: {strategy_id}")
    rows = load_ticker_rows(strategy_id, doc)
    pool = trades_pool_from_ticker_rows(rows)
    params = default_diversified_params(
        initial_cash_jpy=initial_cash_jpy,
        max_positions=max_positions,
        position_pct=position_pct,
    )
    pool = filter_trades_after(pool, entry_after)
    sim = simulate_diversified_portfolio(pool, **params)
    n_with_series = sum(1 for r in rows if ticker_row_has_series(r))
    return {
        "strategy_id": strategy_id,
        "source": "experiments",
        "n_tickers": len(rows),
        "n_tickers_with_trades": len({t for t in pool["ticker"].unique()}) if not pool.empty else 0,
        "n_tickers_with_series": n_with_series,
        "n_trades_in_pool": len(pool),
        "entry_after": str(entry_after) if entry_after is not None else None,
        **params,
        **sim,
    }


def trades_pool_from_backtest_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for row in rows:
        if row.get("error"):
            continue
        compact = row.get(TRADES_COMPACT_KEY)
        if compact:
            trades = unpack_trades(compact)
        else:
            raw = row.get("trades")
            if not raw:
                continue
            trades = pd.DataFrame(raw)
        if trades.empty:
            continue
        trades = trades.copy()
        trades["ticker"] = row.get("ticker") or "?"
        if "entry_time" in trades.columns:
            trades["entry_time"] = pd.to_datetime(trades["entry_time"])
        if "exit_time" in trades.columns:
            trades["exit_time"] = pd.to_datetime(trades["exit_time"])
        frames.append(trades)
    if not frames:
        return pd.DataFrame()
    pool = pd.concat(frames, ignore_index=True)
    return pool.sort_values("entry_time").reset_index(drop=True)
