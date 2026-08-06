from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def plot_price_and_trades(
    df: pd.DataFrame,
    trades: pd.DataFrame,
    title: str = "Price & Trades",
) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="OHLC",
        )
    )
    for col, name in [("ema20", "EMA20"), ("ema50", "EMA50"), ("ema200", "EMA200"), ("vwap", "VWAP")]:
        if col in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[col], name=name, line=dict(width=1)))

    if not trades.empty:
        longs = trades[trades["side"] == "long"]
        shorts = trades[trades["side"] == "short"]
        if not longs.empty:
            fig.add_trace(
                go.Scatter(
                    x=longs["entry_time"],
                    y=longs["entry_price"],
                    mode="markers",
                    marker=dict(symbol="triangle-up", size=11, color="#22c55e", line=dict(width=1, color="white")),
                    name="Long entry",
                    text=[f"PnL {r:.1f}%" for r in longs.get("pnl_pct", [])],
                    hovertemplate="Entry %{x}<br>Price %{y:.2f}<br>%{text}<extra></extra>",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=longs["exit_time"],
                    y=longs["exit_price"],
                    mode="markers",
                    marker=dict(symbol="x", size=9, color="#16a34a"),
                    name="Long exit",
                )
            )
        if not shorts.empty:
            fig.add_trace(
                go.Scatter(
                    x=shorts["entry_time"],
                    y=shorts["entry_price"],
                    mode="markers",
                    marker=dict(symbol="triangle-down", size=11, color="#ef4444"),
                    name="Short entry",
                )
            )

    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        height=480,
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def plot_equity_and_drawdown(equity: pd.Series, title: str = "Equity & Drawdown") -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35], vertical_spacing=0.06)

    fig.add_trace(
        go.Scatter(x=equity.index, y=equity, name="Equity", line=dict(color="#3b82f6", width=2), fill="tozeroy"),
        row=1,
        col=1,
    )

    rolling_max = equity.cummax()
    dd = (equity - rolling_max) / rolling_max * 100
    fig.add_trace(
        go.Scatter(x=dd.index, y=dd, name="Drawdown %", line=dict(color="#f97316", width=1.5), fill="tozeroy"),
        row=2,
        col=1,
    )
    fig.add_hline(y=0, line_dash="dot", line_color="gray", row=2, col=1)

    fig.update_yaxes(title_text="USD", row=1, col=1)
    fig.update_yaxes(title_text="DD %", row=2, col=1)
    fig.update_layout(title=title, height=520, template="plotly_dark", showlegend=False)
    return fig


def plot_trade_pnl(trades: pd.DataFrame, title: str = "Trade PnL") -> go.Figure:
    if trades.empty:
        fig = go.Figure()
        fig.update_layout(title="取引データなし", template="plotly_dark")
        return fig

    df = trades.copy()
    df["trade_num"] = range(1, len(df) + 1)
    colors = ["#22c55e" if p > 0 else "#ef4444" for p in df["pnl_pct"]]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["trade_num"],
            y=df["pnl_pct"],
            marker_color=colors,
            name="PnL %",
            text=[f"{p:+.1f}%" for p in df["pnl_pct"]],
            textposition="outside",
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title=title,
        xaxis_title="Trade #",
        yaxis_title="Net PnL %",
        height=360,
        template="plotly_dark",
    )
    return fig


def plot_cumulative_pnl(trades: pd.DataFrame, title: str = "Cumulative PnL") -> go.Figure:
    if trades.empty:
        fig = go.Figure()
        fig.update_layout(title="取引データなし", template="plotly_dark")
        return fig

    cum = trades["pnl_pct"].cumsum()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=list(range(1, len(cum) + 1)),
            y=cum,
            mode="lines+markers",
            line=dict(color="#a855f7", width=2),
            name="Cumulative PnL %",
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(title=title, xaxis_title="Trade #", yaxis_title="Cumulative PnL %", height=360, template="plotly_dark")
    return fig


def plot_strategy_comparison(rows: list[dict[str, Any]], metric: str = "profit_factor") -> go.Figure:
    if not rows:
        fig = go.Figure()
        fig.update_layout(title="比較データなし", template="plotly_dark")
        return fig

    df = pd.DataFrame(rows)
    colors = ["#22c55e" if v >= 1.05 else "#eab308" if v >= 1.0 else "#ef4444" for v in df[metric]]
    fig = go.Figure(
        go.Bar(
            x=df["strategy"],
            y=df[metric],
            marker_color=colors,
            text=[f"{v:.2f}" for v in df[metric]],
            textposition="outside",
        )
    )
    fig.add_hline(y=1.0, line_dash="dash", line_color="white", annotation_text="損益分岐 PF=1.0")
    fig.update_layout(title=f"戦略比較 — {metric}", yaxis_title=metric, height=400, template="plotly_dark")
    return fig


def plot_cost_comparison(rows: list[dict[str, Any]]) -> go.Figure:
    if not rows:
        fig = go.Figure()
        fig.update_layout(title="コストデータなし", template="plotly_dark")
        return fig

    df = pd.DataFrame(rows)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=df["cost_model"], y=df["profit_factor"], name="PF (net)", marker_color="#3b82f6"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=df["cost_model"], y=df["total_cost_usd"], name="Total cost $", mode="lines+markers"),
        secondary_y=True,
    )
    fig.update_layout(title="コストモデル別 PF vs 総コスト", height=420, template="plotly_dark")
    fig.update_yaxes(title_text="Profit Factor", secondary_y=False)
    fig.update_yaxes(title_text="Cost (USD)", secondary_y=True)
    return fig


def plot_cost_breakdown(trades: pd.DataFrame) -> go.Figure:
    if trades.empty or "total_fees_usd" not in trades.columns:
        fig = go.Figure()
        fig.update_layout(title="コスト内訳なし（legacy モデル等）", template="plotly_dark")
        return fig

    fees = float(trades["total_fees_usd"].sum())
    slip = float(trades.get("total_slippage_usd", pd.Series([0])).sum())
    labels = ["規制費用 (SEC/TAF/CAT)", "スリッページ"]
    values = [fees, slip]
    fig = px.pie(names=labels, values=values, title="取引コスト内訳", color_discrete_sequence=["#6366f1", "#f97316"])
    fig.update_layout(template="plotly_dark", height=380)
    return fig


def plot_oos_comparison(full_metrics: dict, oos_metrics: dict) -> go.Figure:
    labels = ["Win rate", "Profit Factor", "Sharpe×10"]
    full_vals = [
        full_metrics.get("win_rate", 0) * 100,
        full_metrics.get("profit_factor", 0),
        full_metrics.get("sharpe", 0) * 10,
    ]
    oos_vals = [
        oos_metrics.get("win_rate", 0) * 100,
        oos_metrics.get("profit_factor", 0),
        oos_metrics.get("sharpe", 0) * 10,
    ]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="全期間", x=labels, y=full_vals, marker_color="#64748b"))
    fig.add_trace(go.Bar(name="OOS (ML)", x=labels, y=oos_vals, marker_color="#22c55e"))
    fig.update_layout(title="全期間 vs OOS メトリクス", barmode="group", height=380, template="plotly_dark")
    return fig
