"""Compact trade/equity series on experiment sidecars — slice metrics without re-backtest."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from signalforge.backtest.metrics import compute_metrics
from signalforge.compare.runner import _aggregate
from signalforge.experiments.storage import rows_for_universe_aggregate, ticker_row_has_core_metrics

SERIES_SCHEMA = "trades_equity_v1"

# Sidecar keys (kept by compact_ticker_row)
TRADES_COMPACT_KEY = "trades_compact"
EQUITY_DAILY_KEY = "equity_daily"


def ticker_row_has_series(row: dict[str, Any]) -> bool:
    if row.get("error"):
        return False
    trades = row.get(TRADES_COMPACT_KEY)
    eq = row.get(EQUITY_DAILY_KEY)
    return isinstance(trades, list) and isinstance(eq, dict) and bool(eq.get("d"))


def pack_trades(trades: pd.DataFrame) -> list[dict[str, Any]]:
    if trades is None or trades.empty:
        return []
    out: list[dict[str, Any]] = []
    for _, t in trades.iterrows():
        exit_t = t.get("exit_time")
        entry_t = t.get("entry_time")
        if exit_t is None:
            continue
        item: dict[str, Any] = {
            "x": pd.Timestamp(exit_t).strftime("%Y-%m-%d"),
            "p": float(t.get("pnl_pct") or 0.0),
        }
        if entry_t is not None:
            item["e"] = pd.Timestamp(entry_t).strftime("%Y-%m-%d")
        if t.get("gross_pnl_pct") is not None:
            item["g"] = float(t["gross_pnl_pct"])
        if t.get("hold_bars") is not None:
            item["h"] = int(t["hold_bars"])
        if t.get("total_cost_usd") is not None:
            item["c"] = float(t["total_cost_usd"])
        if t.get("entry_price") is not None and pd.notna(t.get("entry_price")):
            item["ep"] = float(t["entry_price"])
        if t.get("exit_price") is not None and pd.notna(t.get("exit_price")):
            item["xp"] = float(t["exit_price"])
        out.append(item)
    return out


def pack_equity_daily(equity: pd.Series) -> dict[str, Any]:
    if equity is None or len(equity) == 0:
        return {"d": [], "v": []}
    s = equity.sort_index()
    daily = s.resample("D").last().dropna()
    return {
        "d": [ts.strftime("%Y-%m-%d") for ts in daily.index],
        "v": [float(v) for v in daily.values],
    }


def series_fields_from_backtest(trades: pd.DataFrame, equity: pd.Series) -> dict[str, Any]:
    return {
        TRADES_COMPACT_KEY: pack_trades(trades),
        EQUITY_DAILY_KEY: pack_equity_daily(equity),
        "series_schema": SERIES_SCHEMA,
    }


def _parse_ts(d: str | None) -> pd.Timestamp | None:
    if not d:
        return None
    return pd.Timestamp(str(d)[:10])


def unpack_equity(daily: dict[str, Any]) -> pd.Series:
    dates = daily.get("d") or []
    vals = daily.get("v") or []
    if not dates or len(dates) != len(vals):
        return pd.Series(dtype=float)
    idx = pd.to_datetime(dates)
    return pd.Series([float(v) for v in vals], index=idx).sort_index()


def unpack_trades(compact: list[dict[str, Any]]) -> pd.DataFrame:
    if not compact:
        return pd.DataFrame()
    rows = []
    for t in compact:
        exit_t = _parse_ts(t.get("x"))
        if exit_t is None:
            continue
        entry_t = _parse_ts(t.get("e"))
        row: dict[str, Any] = {
            "exit_time": exit_t,
            "entry_time": entry_t if entry_t is not None else exit_t,
            "pnl_pct": float(t.get("p") or 0.0),
        }
        if t.get("g") is not None:
            row["gross_pnl_pct"] = float(t["g"])
        if t.get("h") is not None:
            row["hold_bars"] = int(t["h"])
        if t.get("c") is not None:
            row["total_cost_usd"] = float(t["c"])
        if t.get("ep") is not None:
            row["entry_price"] = float(t["ep"])
        if t.get("xp") is not None:
            row["exit_price"] = float(t["xp"])
        rows.append(row)
    return pd.DataFrame(rows)


def period_sliceable(
    start: date | None,
    end: date | None,
    stored_start: date | None,
    stored_end: date | None,
) -> bool:
    """True if requested window lies inside the stored backtest span."""
    if start is None or stored_start is None:
        return False
    if start < stored_start:
        return False
    if stored_end is not None and end is not None and end > stored_end:
        return False
    return True


def slice_row_metrics(
    row: dict[str, Any],
    start: date | None,
    end: date | None,
) -> dict[str, Any] | None:
    """Recompute top-level metrics for a sub-window (exit date filter + equity slice)."""
    if not ticker_row_has_series(row):
        return None
    ts = pd.Timestamp(start) if start else None
    te = pd.Timestamp(end) if end else None

    trades = unpack_trades(row.get(TRADES_COMPACT_KEY) or [])
    equity = unpack_equity(row.get(EQUITY_DAILY_KEY) or {})
    if equity.empty:
        return None

    if ts is not None:
        equity = equity[equity.index >= ts.normalize()]
    if te is not None:
        equity = equity[equity.index <= te.normalize()]
    if len(equity) < 2:
        return None

    if not trades.empty:
        exits = pd.to_datetime(trades["exit_time"])
        mask = pd.Series(True, index=trades.index)
        if ts is not None:
            mask &= exits >= ts.normalize()
        if te is not None:
            mask &= exits <= te.normalize()
        trades = trades.loc[mask]

    metrics = compute_metrics(trades, equity)
    return {
        "profit_factor": metrics.get("profit_factor"),
        "gross_profit_factor": metrics.get("gross_profit_factor"),
        "win_rate": metrics.get("win_rate"),
        "total_trades": metrics.get("total_trades"),
        "total_return_pct": metrics.get("total_return_pct"),
        "avg_pnl_pct": metrics.get("avg_pnl_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe": metrics.get("sharpe"),
        "sortino": metrics.get("sortino"),
        "total_fees_usd": metrics.get("total_fees_usd"),
        "total_slippage_usd": metrics.get("total_slippage_usd"),
        "total_cost_usd": metrics.get("total_cost_usd"),
        "avg_cost_per_trade_usd": metrics.get("avg_cost_per_trade_usd"),
        "avg_hold_bars": metrics.get("avg_hold_bars"),
    }


def strategy_series_coverage(rows: list[dict[str, Any]]) -> tuple[int, int]:
    ok = [r for r in rows if not r.get("error")]
    with_series = [r for r in ok if ticker_row_has_series(r)]
    return len(with_series), len(ok)


def aggregate_sliced_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    agg_in = rows_for_universe_aggregate(rows)
    return _aggregate(agg_in if agg_in else rows)
