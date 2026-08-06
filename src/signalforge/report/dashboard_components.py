from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from signalforge.backtest.metrics import compute_metrics
from signalforge.report.dashboard_glossary import METRIC_HELP


def verdict_badge(pf: float, total_return: float) -> tuple[str, str]:
    if pf >= 1.05 and total_return > 0:
        return "✅ 利益余地あり", "success"
    if pf >= 1.0:
        return "⚠️ ギリギリ（エッジ薄い）", "warning"
    return "❌ 期待値マイナス", "error"


def render_metric_row(metrics: dict[str, Any], prefix: str = "") -> None:
    pf_key = "OOS PF" if prefix.strip() else "PF"
    win_key = "OOS Win率" if prefix.strip() else "Win率"
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        f"{prefix}損益比(PF)",
        f"{metrics.get('profit_factor', 0):.2f}",
        help=METRIC_HELP.get(pf_key, METRIC_HELP["PF"]),
    )
    c2.metric(
        f"{prefix}Win率",
        f"{metrics.get('win_rate', 0):.1%}",
        help=METRIC_HELP.get(win_key, METRIC_HELP["Win率"]),
    )
    c3.metric(
        f"{prefix}Sharpe",
        f"{metrics.get('sharpe', 0):.2f}",
        help=METRIC_HELP["Sharpe"],
    )
    c4.metric(
        f"{prefix}Max DD",
        f"{metrics.get('max_drawdown_pct', 0):.1f}%",
        help=METRIC_HELP["Max DD"],
    )
    c5.metric(
        f"{prefix}取引数",
        f"{metrics.get('total_trades', 0)}",
        help=METRIC_HELP["取引数"],
    )


def render_cost_row(metrics: dict[str, Any]) -> None:
    if not metrics.get("total_cost_usd"):
        return
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "規制費用",
        f"${metrics.get('total_fees_usd', 0):,.0f}",
        help=METRIC_HELP["規制費用"],
    )
    c2.metric(
        "スリッページ",
        f"${metrics.get('total_slippage_usd', 0):,.0f}",
        help=METRIC_HELP["スリッページ"],
    )
    c3.metric(
        "1取引あたりコスト",
        f"${metrics.get('avg_cost_per_trade_usd', 0):,.0f}",
        help=METRIC_HELP["1取引あたりコスト"],
    )


def trades_dataframe(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades
    cols = [
        "entry_time",
        "exit_time",
        "side",
        "entry_price",
        "exit_price",
        "pnl_pct",
        "gross_pnl_pct",
        "hold_bars",
        "reason",
        "is_oos",
        "total_cost_usd",
    ]
    present = [c for c in cols if c in trades.columns]
    out = trades[present].copy()
    if "is_oos" in out.columns:
        out["is_oos"] = out["is_oos"].map({True: "OOS", False: "IS"})
    return out


def oos_metrics_from_trades(trades: pd.DataFrame, equity: pd.Series) -> dict[str, Any]:
    if trades.empty or "is_oos" not in trades.columns:
        return compute_metrics(pd.DataFrame(), equity)
    oos = trades[trades["is_oos"]]
    return compute_metrics(oos, equity)


def render_verdict_panel(metrics: dict[str, Any], cost_model: str) -> None:
    pf = metrics.get("profit_factor", 0)
    ret = metrics.get("total_return_pct", 0)
    label, level = verdict_badge(pf, ret)
    detail = (
        f"損益比(PF)={pf:.2f}、総リターン {ret:.1f}%（{cost_model} コスト込み）。"
        "PF≥1.05 かつリターン>0 なら「利益余地あり」。"
    )
    if level == "success":
        st.success(f"**{label}** — {detail}")
    elif level == "warning":
        st.warning(f"**{label}** — {detail}")
    else:
        st.error(f"**{label}** — {detail}")
