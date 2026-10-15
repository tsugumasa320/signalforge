"""Capital-constrained portfolio simulation (Izanami 最適分散投資 approximation)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def equity_daily_from_accepted(
    initial_capital: float,
    accepted: list[dict],
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.Series:
    """Step equity at each exit; daily forward-fill (for charts)."""
    if end is None:
        end = pd.Timestamp.now(tz="UTC").normalize()
    if start is None:
        start = end
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")

    if not accepted:
        idx = pd.date_range(start.normalize(), end.normalize(), freq="D", tz="UTC")
        return pd.Series(float(initial_capital), index=idx)

    cash = float(initial_capital)
    points: list[tuple[pd.Timestamp, float]] = [(start.normalize(), cash)]
    rows = sorted(accepted, key=lambda r: pd.Timestamp(r["exit_ts"]))
    for row in rows:
        cash += float(row.get("pnl_jpy") or 0.0)
        ts = pd.Timestamp(row["exit_ts"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        points.append((ts.normalize(), cash))

    series = pd.Series({t: v for t, v in points}).sort_index()
    daily = series.resample("D").last().ffill()
    idx = pd.date_range(start.normalize(), end.normalize(), freq="D", tz="UTC")
    return daily.reindex(idx).ffill().fillna(float(initial_capital))


def simulate_diversified_portfolio(
    trades: pd.DataFrame,
    *,
    initial_capital: float = 1_000_000.0,
    max_positions: int = 5,
    position_pct: float | None = None,
    chart_start: pd.Timestamp | None = None,
    chart_end: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """
    Greedy non-overlapping: earliest entry first, skip if slot full until exit frees capital.
    Each trade uses fixed notional fraction of *current* equity at entry.
    """
    if trades.empty:
        end = chart_end or pd.Timestamp.now(tz="UTC")
        start = chart_start or end
        empty_eq = equity_daily_from_accepted(initial_capital, [], start=start, end=end)
        return {
            "final_equity": initial_capital,
            "total_return_pct": 0.0,
            "accepted_trades": 0,
            "skipped_overlap": 0,
            "skipped": 0,
            "equity_daily": _pack_equity_daily(empty_eq),
        }

    t = trades.sort_values("entry_time").copy()
    t["entry_ts"] = pd.to_datetime(t["entry_time"])
    t["exit_ts"] = pd.to_datetime(t["exit_time"])
    cash = initial_capital
    open_slots: list[dict] = []
    accepted: list[dict] = []
    skipped = 0
    pct = position_pct if position_pct is not None else min(1.0 / max(max_positions, 1), 0.2)

    for _, row in t.iterrows():
        open_slots = [s for s in open_slots if s["exit_ts"] > row["entry_ts"]]
        if len(open_slots) >= max_positions:
            skipped += 1
            continue
        notional = cash * pct
        if notional <= 0:
            skipped += 1
            continue
        pnl_frac = float(row["pnl_pct"]) / 100.0
        cash += notional * pnl_frac
        exit_ts = row["exit_ts"]
        open_slots.append({"exit_ts": exit_ts})
        accepted.append(
            {
                **row.to_dict(),
                "notional": notional,
                "pnl_jpy": notional * pnl_frac,
                "exit_ts": exit_ts,
            }
        )

    ret = (cash / initial_capital - 1) * 100 if initial_capital else 0.0
    start_ts = chart_start or pd.to_datetime(t["entry_ts"].min())
    end_ts = chart_end or pd.to_datetime(t["exit_ts"].max())
    eq = equity_daily_from_accepted(initial_capital, accepted, start=start_ts, end=end_ts)
    return {
        "initial_capital": initial_capital,
        "final_equity": cash,
        "total_return_pct": ret,
        "accepted_trades": len(accepted),
        "skipped_overlap": skipped,
        "skipped": skipped,
        "max_positions": max_positions,
        "position_pct": pct,
        "equity_daily": _pack_equity_daily(eq),
    }


def _pack_equity_daily(equity: pd.Series) -> dict[str, list]:
    if equity is None or len(equity) == 0:
        return {"d": [], "v": []}
    s = equity.sort_index()
    return {
        "d": [ts.strftime("%Y-%m-%d") for ts in s.index],
        "v": [float(v) for v in s.values],
    }


def unpack_equity_daily(daily: dict) -> pd.Series:
    dates = daily.get("d") or []
    vals = daily.get("v") or []
    if not dates or len(dates) != len(vals):
        return pd.Series(dtype=float)
    idx = pd.to_datetime(dates, utc=True)
    return pd.Series([float(v) for v in vals], index=idx).sort_index()
