"""Capital-constrained portfolio simulation (Izanami 最適分散投資 approximation)."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from signalforge.portfolio.liquidity import ticker_liquidity_score_map

EntryPriority = Literal[
    "first_come",
    "liquidity",
    "sector_liquidity",
    "sector_random",
    "sector_kairi",
    "sector_history",
    "sector_turnover",
]
RegimeFilter = Literal["none", "ma200", "crash_guard", "ma200_crash"]

ENTRY_PRIORITIES: tuple[str, ...] = (
    "first_come",
    "liquidity",
    "sector_liquidity",
    "sector_random",
    "sector_kairi",
    "sector_history",
    "sector_turnover",
)
REGIME_FILTERS: tuple[str, ...] = ("none", "ma200", "crash_guard", "ma200_crash")
CRASH_GUARD_RET5_PCT = -4.0

DEFAULT_ENTRY_RULES: dict[str, Any] = {
    "entry_priority": "sector_turnover",
    "min_turnover_jpy": 5e8,
    "min_breadth_rank": 0.8,
    "regime_filter": "none",
}
LEGACY_ENTRY_RULES: dict[str, Any] = {
    "entry_priority": "sector_liquidity",
    "min_turnover_jpy": 0.0,
    "min_breadth_rank": 0.0,
    "regime_filter": "none",
}


def _attach_features(
    t: pd.DataFrame,
    entry_priority: str,
    regime_filter: str,
    min_turnover_jpy: float = 0.0,
    min_breadth_rank: float = 0.0,
) -> pd.DataFrame:
    from signalforge.portfolio import entry_features as ef

    if min_breadth_rank and "breadth_rank" not in t.columns:
        t = ef.attach_breadth(t)
    if entry_priority == "sector_kairi" and "kairi_pct" not in t.columns:
        t = ef.attach_kairi(t)
    if entry_priority == "sector_history" and "hist_mean_pnl" not in t.columns:
        t = ef.attach_ticker_history(t)
    if (entry_priority == "sector_turnover" or min_turnover_jpy) and "turnover_jpy" not in t.columns:
        t = ef.attach_turnover(t)
    if regime_filter != "none" and "mkt_above_ma200" not in t.columns:
        t = ef.attach_regime(t)
    return t


def _regime_mask(t: pd.DataFrame, regime_filter: str) -> pd.Series:
    blocked = pd.Series(False, index=t.index)
    if regime_filter == "none" or t.empty:
        return blocked
    if regime_filter in ("ma200", "ma200_crash"):
        blocked |= ~t["mkt_above_ma200"].astype(bool)
    if regime_filter in ("crash_guard", "ma200_crash"):
        blocked |= t["mkt_ret5_pct"].fillna(0.0) < CRASH_GUARD_RET5_PCT
    return blocked


def _prepare_trade_queue(trades: pd.DataFrame, entry_priority: EntryPriority) -> pd.DataFrame:
    t = trades.copy()
    t["entry_ts"] = pd.to_datetime(t["entry_time"])
    t["exit_ts"] = pd.to_datetime(t["exit_time"])
    if entry_priority in ("first_come", "sector_random"):
        return t.sort_values("entry_ts", kind="mergesort")
    if "ticker" in t.columns:
        t["_liq"] = t["ticker"].astype(str).map(ticker_liquidity_score_map()).fillna(0.0)
    else:
        t["_liq"] = 0.0
    score_col = {
        "sector_kairi": ("kairi_pct", -1.0),
        "sector_history": ("hist_mean_pnl", 1.0),
        "sector_turnover": ("turnover_jpy", 1.0),
    }.get(entry_priority)
    if score_col is not None:
        col, sign = score_col
        t["_score"] = sign * t[col].fillna(0.0)
        return t.sort_values(["entry_ts", "_score", "_liq"], ascending=[True, False, False], kind="mergesort")
    return t.sort_values(["entry_ts", "_liq"], ascending=[True, False], kind="mergesort")


def _uses_sector_cap(entry_priority: str) -> bool:
    return entry_priority.startswith("sector_")


def max_drawdown_pct(equity: pd.Series) -> float:
    if equity is None or len(equity) == 0:
        return 0.0
    peak = equity.cummax()
    dd = (equity / peak - 1.0) * 100.0
    return float(dd.min())


def period_return_pct(equity: pd.Series, start: str | None = None, end: str | None = None) -> float | None:
    if equity is None or len(equity) == 0:
        return None
    s = equity.sort_index()
    if start:
        s = s[s.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        s = s[s.index < pd.Timestamp(end, tz="UTC")]
    if len(s) < 2:
        return None
    base = equity[equity.index < s.index[0]]
    first = float(base.iloc[-1]) if len(base) else float(s.iloc[0])
    return (float(s.iloc[-1]) / first - 1.0) * 100.0 if first else None


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
    entry_priority: EntryPriority = "liquidity",
    max_per_sector: int = 2,
    regime_filter: RegimeFilter = "none",
    tie_break_seed: int | None = None,
    min_turnover_jpy: float = 0.0,
    min_breadth_rank: float = 0.0,
) -> dict[str, Any]:
    """
    min_breadth_rank: only enter on days whose signal count ranks at/above this share of the trailing year.
    tie_break_seed: shuffle same-score candidates (otherwise input order decides ties, e.g. ticker code).
    min_turnover_jpy: skip signals whose 20-day mean trading value before entry is below this.
    Greedy non-overlapping queue; skip if slot full until exit frees capital.
    entry_priority: liquidity = same-day tie-break by liquid names; sector_* also caps sector overlap.
    sector_kairi ranks deepest 25MA kairi first; sector_history ranks by the ticker's prior realized pnl.
    regime_filter blocks new entries from the previous benchmark close (1321.T).
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
            "fills": [],
            "entry_priority": entry_priority,
            "regime_filter": regime_filter,
        }

    t = _attach_features(trades, entry_priority, regime_filter, min_turnover_jpy, min_breadth_rank)
    skipped_turnover = 0
    if min_turnover_jpy:
        thin = t["turnover_jpy"].fillna(0.0) < float(min_turnover_jpy)
        skipped_turnover = int(thin.sum())
        t = t.loc[~thin]
    skipped_breadth = 0
    if min_breadth_rank:
        quiet = t["breadth_rank"].fillna(0.0) < float(min_breadth_rank)
        skipped_breadth = int(quiet.sum())
        t = t.loc[~quiet]
    if tie_break_seed is not None:
        t = t.sample(frac=1.0, random_state=tie_break_seed)
    t = _prepare_trade_queue(t, entry_priority)
    blocked = _regime_mask(t, regime_filter)
    skipped_regime = int(blocked.sum())
    t = t.loc[~blocked]
    cash = initial_capital
    open_slots: list[tuple[Any, str]] = []
    accepted_idx: list[Any] = []
    accepted_notional: list[float] = []
    skipped = 0
    pct = position_pct if position_pct is not None else min(1.0 / max(max_positions, 1), 0.2)
    cap_sector = _uses_sector_cap(entry_priority) and "sector_tse" in t.columns

    entry_arr = t["entry_ts"].to_numpy()
    exit_arr = t["exit_ts"].to_numpy()
    pnl_arr = t["pnl_pct"].astype(float).to_numpy() / 100.0
    sec_arr = t["sector_tse"].fillna("").astype(str).to_numpy() if cap_sector else None
    index_arr = t.index.to_numpy()

    for i in range(len(t)):
        entry_ts = entry_arr[i]
        open_slots = [s for s in open_slots if s[0] > entry_ts]
        if len(open_slots) >= max_positions:
            skipped += 1
            continue
        sec = sec_arr[i] if sec_arr is not None else ""
        if sec and sum(1 for s in open_slots if s[1] == sec) >= max_per_sector:
            skipped += 1
            continue
        notional = cash * pct
        if notional <= 0:
            skipped += 1
            continue
        cash += notional * pnl_arr[i]
        open_slots.append((exit_arr[i], sec))
        accepted_idx.append(index_arr[i])
        accepted_notional.append(notional)

    acc_df = t.loc[accepted_idx].copy()
    acc_df["notional"] = accepted_notional
    acc_df["pnl_jpy"] = acc_df["notional"] * acc_df["pnl_pct"].astype(float) / 100.0
    accepted = acc_df.to_dict("records")

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
        "skipped_regime": skipped_regime,
        "skipped_turnover": skipped_turnover,
        "min_turnover_jpy": float(min_turnover_jpy or 0.0),
        "skipped_breadth": skipped_breadth,
        "min_breadth_rank": float(min_breadth_rank or 0.0),
        "max_positions": max_positions,
        "position_pct": pct,
        "max_drawdown_pct": max_drawdown_pct(eq),
        "win_rate_pct": (sum(1 for a in accepted if a["pnl_jpy"] > 0) / len(accepted) * 100.0) if accepted else None,
        "equity_daily": _pack_equity_daily(eq),
        "fills": pack_fills(accepted),
        "entry_priority": entry_priority,
        "regime_filter": regime_filter,
    }


def _fill_date(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _fill_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pack_fills(accepted: list[dict]) -> list[dict]:
    """JSON-safe accepted trades: ticker, dates, prices, yen PnL."""
    rows = []
    for row in accepted:
        item = {
            "ticker": str(row.get("ticker") or ""),
            "entry_time": _fill_date(row.get("entry_time")),
            "exit_time": _fill_date(row.get("exit_time")),
            "entry_price": _fill_float(row.get("entry_price")),
            "exit_price": _fill_float(row.get("exit_price")),
            "pnl_pct": _fill_float(row.get("pnl_pct")),
            "pnl_jpy": _fill_float(row.get("pnl_jpy")),
            "notional": _fill_float(row.get("notional")),
        }
        side = row.get("side")
        if side:
            item["side"] = str(side)
        rows.append(item)
    rows.sort(key=lambda r: (r.get("exit_time") or "", r.get("entry_time") or "", r.get("ticker") or ""))
    return rows


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
