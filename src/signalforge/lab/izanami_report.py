"""Full result summary (Izanami 結果概要)."""

from __future__ import annotations

import statistics
from typing import Any

import pandas as pd


def expectancy_formula(wins: pd.DataFrame, losses: pd.DataFrame) -> float:
    if wins.empty and losses.empty:
        return 0.0
    n = len(wins) + len(losses)
    wr = len(wins) / n
    lr = len(losses) / n
    avg_win = float(wins["pnl_pct"].mean()) if len(wins) else 0.0
    avg_loss = float(losses["pnl_pct"].mean()) if len(losses) else 0.0
    return avg_win * wr + avg_loss * lr


def build_overview_report(
    trades: pd.DataFrame,
    *,
    rule_name: str,
    fill_stats: dict[str, int] | None = None,
    ticker_meta: dict[str, dict] | None = None,
    elapsed_sec: float = 0.0,
) -> dict[str, Any]:
    fill_stats = fill_stats or {}
    if trades.empty:
        return {"rule_name": rule_name, "total_trades": 0, "elapsed_sec": elapsed_sec}

    pnl = trades["pnl_pct"].astype(float)
    wins = trades[pnl > 0]
    losses = trades[pnl <= 0]
    gross_profit = float(wins["pnl_pct"].sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses["pnl_pct"].sum())) if len(losses) else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0
    avg_win = float(wins["pnl_pct"].mean()) if len(wins) else 0.0
    avg_loss = float(losses["pnl_pct"].mean()) if len(losses) else 0.0
    exp = expectancy_formula(wins, losses)
    payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 999.0

    total_sig = fill_stats.get("total_entry_signals") or len(trades)
    filled = fill_stats.get("filled") or len(trades)
    fill_rate = filled / total_sig if total_sig else 0.0

    # Daily aggregation
    t = trades.copy()
    t["exit_date"] = pd.to_datetime(t["exit_time"]).dt.date
    daily = t.groupby("exit_date")["pnl_pct"].agg(["sum", "mean", "count"])
    daily_exp_positive = 0.0
    if len(daily):
        pos_days = (daily["mean"] > 0).sum()
        daily_exp_positive = pos_days / len(daily)

    tickers_traded = t["ticker"].nunique() if "ticker" in t.columns else 0

    report = {
        "rule_name": rule_name,
        "elapsed_sec": round(elapsed_sec, 2),
        "total_trades": len(trades),
        "total_entry_signals": total_sig,
        "fill_rate": fill_rate,
        "unfilled": {
            "limit": fill_stats.get("unfilled_limit", 0),
            "no_volume": fill_stats.get("unfilled_no_volume", 0),
            "stop_limit": fill_stats.get("unfilled_stop_limit", 0),
        },
        "win_rate": len(wins) / len(trades),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "expectancy_pct": exp,
        "payoff_ratio": payoff,
        "profit_factor": pf if pf != 999.0 else 999.0,
        "median_pnl_pct": float(pnl.median()),
        "std_win_pct": float(wins["pnl_pct"].std()) if len(wins) > 1 else 0.0,
        "std_loss_pct": float(losses["pnl_pct"].std()) if len(losses) > 1 else 0.0,
        "cumulative_pnl_pct": float(pnl.sum()),
        "avg_hold_bars": float(trades["hold_bars"].mean()) if "hold_bars" in trades else 0.0,
        "max_hold_bars": int(trades["hold_bars"].max()) if "hold_bars" in trades else 0,
        "min_hold_bars": int(trades["hold_bars"].min()) if "hold_bars" in trades else 0,
        "win_rate_daily": daily_exp_positive,
        "median_pnl_daily": float(daily["mean"].median()) if len(daily) else 0.0,
        "tickers_traded": tickers_traded,
        "trades_per_ticker": len(trades) / tickers_traded if tickers_traded else 0.0,
        "pnl_buckets": _buckets(pnl),
    }
    report["aggregations"] = {
        "by_year": aggregate_by(trades, "year"),
        "by_ticker": aggregate_by(trades, "ticker") if "ticker" in trades.columns else {},
        "by_segment": aggregate_by_meta(trades, ticker_meta, "segment"),
        "by_sector_tse": aggregate_by_meta(trades, ticker_meta, "sector_tse"),
        "by_hold_bars": aggregate_by_hold(trades),
    }
    return report


def _buckets(pnl: pd.Series) -> dict[str, int]:
    return {
        "lte_-5": int((pnl <= -5).sum()),
        "m5_m2": int(((pnl > -5) & (pnl <= -2)).sum()),
        "m2_0": int(((pnl > -2) & (pnl <= 0)).sum()),
        "0_2": int(((pnl > 0) & (pnl <= 2)).sum()),
        "2_5": int(((pnl > 2) & (pnl <= 5)).sum()),
        "gt_5": int((pnl > 5).sum()),
    }


def aggregate_by(trades: pd.DataFrame, kind: str) -> dict[str, Any]:
    if trades.empty:
        return {}
    t = trades.copy()
    if kind == "year":
        t["_key"] = pd.to_datetime(t["exit_time"]).dt.year.astype(str)
    elif kind == "ticker":
        if "ticker" not in t.columns:
            return {}
        t["_key"] = t["ticker"]
    else:
        return {}
    out = {}
    for key, grp in t.groupby("_key"):
        pnl = grp["pnl_pct"].astype(float)
        wins = grp[pnl > 0]
        losses = grp[pnl <= 0]
        out[str(key)] = {
            "trades": len(grp),
            "expectancy_pct": expectancy_formula(wins, losses),
            "win_rate": len(wins) / len(grp) if len(grp) else 0,
        }
    return out


def aggregate_by_meta(trades: pd.DataFrame, meta: dict[str, dict] | None, field: str) -> dict[str, Any]:
    if not meta or "ticker" not in trades.columns:
        return {}
    t = trades.copy()
    t["_key"] = t["ticker"].map(lambda s: (meta.get(s) or {}).get(field, "unknown"))
    return _group_key(t)


def _group_key(t: pd.DataFrame) -> dict[str, Any]:
    out = {}
    for key, grp in t.groupby("_key"):
        pnl = grp["pnl_pct"].astype(float)
        wins = grp[pnl > 0]
        losses = grp[pnl <= 0]
        out[str(key)] = {
            "trades": len(grp),
            "expectancy_pct": expectancy_formula(wins, losses),
            "win_rate": len(wins) / len(grp) if len(grp) else 0,
        }
    return out


def aggregate_by_hold(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty or "hold_bars" not in trades:
        return {}
    t = trades.copy()
    t["_key"] = pd.cut(
        t["hold_bars"],
        bins=[0, 3, 7, 15, 999],
        labels=["1-3", "4-7", "8-15", "16+"],
    ).astype(str)
    return _group_key(t)
