"""Illustrative strategy diagrams for the dashboard guide tab."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Shared colors
C_ENTRY = "#22c55e"
C_SHORT = "#ef4444"
C_SIGNAL = "#fbbf24"
C_ZONE = "rgba(59, 130, 246, 0.15)"
C_ZONE_WARN = "rgba(251, 191, 36, 0.2)"
C_VWAP = "#a78bfa"
C_EMA = "#38bdf8"
C_EMA200 = "#64748b"


def _base_layout(fig: go.Figure, title: str, height: int = 420) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0.02, font=dict(size=14)),
        template="plotly_dark",
        height=height,
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
    )
    return fig


def _annotate(fig: go.Figure, x, y, text: str, ax: float = 0, ay: float = -40, color: str = C_SIGNAL) -> None:
    fig.add_annotation(
        x=x,
        y=y,
        text=text,
        showarrow=True,
        arrowhead=2,
        arrowcolor=color,
        font=dict(size=11, color=color),
        ax=ax,
        ay=ay,
        bgcolor="rgba(0,0,0,0.6)",
        bordercolor=color,
        borderwidth=1,
    )


def plot_macd_cross_demo() -> go.Figure:
    n = 60
    idx = pd.date_range("2024-06-01", periods=n, freq="D")
    t = np.arange(n)
    close = 120 + 0.35 * t + 3 * np.sin(t / 5)
    close[48:] -= np.linspace(0, 4, n - 48)  # 後半で下落 → 売りシグナル用
    ema50 = pd.Series(close).ewm(span=50).mean().values
    ema200 = pd.Series(close).ewm(span=200).mean().values

    macd_line = pd.Series(close).ewm(span=12).mean() - pd.Series(close).ewm(span=26).mean()
    signal_line = macd_line.ewm(span=9).mean()
    hist = macd_line - signal_line

    entry_i = 42
    short_i = 54
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38], vertical_spacing=0.06)

    fig.add_trace(
        go.Scatter(x=idx, y=close, name="終値", line=dict(color="#e2e8f0", width=2)),
        row=1,
        col=1,
    )
    fig.add_trace(go.Scatter(x=idx, y=ema50, name="EMA50（トレンド）", line=dict(color=C_EMA, width=1.5)), row=1, col=1)
    fig.add_trace(
        go.Scatter(x=idx, y=ema200, name="EMA200", line=dict(color=C_EMA200, width=1, dash="dot")),
        row=1,
        col=1,
    )

    fig.add_vrect(
        x0=idx[entry_i - 2],
        x1=idx[entry_i + 1],
        fillcolor="rgba(34,197,94,0.12)",
        line_width=0,
        row=1,
        col=1,
        annotation_text="🟢 買いゾーン",
        annotation_position="top left",
    )
    fig.add_vrect(
        x0=idx[short_i - 2],
        x1=idx[short_i + 1],
        fillcolor="rgba(239,68,68,0.12)",
        line_width=0,
        row=1,
        col=1,
        annotation_text="🔴 売りゾーン",
        annotation_position="top left",
    )

    fig.add_trace(
        go.Scatter(
            x=[idx[entry_i]],
            y=[close[entry_i]],
            mode="markers+text",
            text=["買い"],
            textposition="top center",
            marker=dict(symbol="triangle-up", size=16, color=C_ENTRY, line=dict(width=2, color="white")),
            name="🟢 買いシグナル",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=[idx[short_i]],
            y=[close[short_i]],
            mode="markers+text",
            text=["売り"],
            textposition="bottom center",
            marker=dict(symbol="triangle-down", size=16, color=C_SHORT, line=dict(width=2, color="white")),
            name="🔴 売りシグナル",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(go.Scatter(x=idx, y=macd_line, name="MACD", line=dict(color="#38bdf8")), row=2, col=1)
    fig.add_trace(go.Scatter(x=idx, y=signal_line, name="シグナル", line=dict(color="#f97316")), row=2, col=1)
    fig.add_trace(
        go.Bar(x=idx, y=hist, name="ヒストグラム", marker_color=["#22c55e" if v >= 0 else "#ef4444" for v in hist]),
        row=2,
        col=1,
    )

    _annotate(fig, idx[entry_i], close[entry_i], "GC + 終値>EMA", ax=50, ay=-50, color=C_ENTRY)
    _annotate(fig, idx[short_i], close[short_i], "DC + 終値<EMA", ax=50, ay=40, color=C_SHORT)

    fig.update_layout(title="MACD クロス — 買い/売りシグナル")
    fig.update_yaxes(title_text="価格", row=1, col=1)
    fig.update_yaxes(title_text="MACD", row=2, col=1)
    return _base_layout(fig, "", height=500)


def plot_ema_pullback_demo() -> go.Figure:
    n = 50
    idx = pd.date_range("2024-03-01", periods=n, freq="D")
    t = np.arange(n)
    close = 100 + 0.5 * t + 2 * np.sin(t / 4)
    ema20 = pd.Series(close).ewm(span=20).mean().values
    ema200 = pd.Series(close).ewm(span=200).mean().values

    touch_i = 35
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=idx, y=close, name="終値", line=dict(color="#e2e8f0", width=2)))
    fig.add_trace(go.Scatter(x=idx, y=ema20, name="EMA20（押し目ライン）", line=dict(color=C_SIGNAL, width=2)))
    fig.add_trace(go.Scatter(x=idx, y=ema200, name="EMA200（大局トレンド）", line=dict(color=C_EMA200, width=1.5)))

    fig.add_hrect(
        y0=ema20[touch_i] * 0.998,
        y1=ema20[touch_i] * 1.002,
        fillcolor=C_ZONE_WARN,
        line_width=0,
        annotation_text="② 安値が EMA20 付近",
        annotation_position="right",
    )

    fig.add_hrect(
        y0=ema200[touch_i] - 2,
        y1=ema200[touch_i] + 50,
        fillcolor="rgba(34,197,94,0.08)",
        line_width=0,
        annotation_text="① 終値 > EMA200",
        annotation_position="left",
    )

    fig.add_trace(
        go.Scatter(
            x=[idx[touch_i]],
            y=[close[touch_i]],
            mode="markers+text",
            text=["買い"],
            textposition="top center",
            marker=dict(symbol="triangle-up", size=16, color=C_ENTRY, line=dict(width=2, color="white")),
            name="🟢 買いシグナル（のみ）",
        )
    )

    _annotate(fig, idx[touch_i], close[touch_i], "③ 反発して終値>EMA20", ax=40, ay=-45, color=C_ENTRY)
    _base_layout(fig, "EMA 押し目買い — 🟢 買いシグナルのみ（売りなし）")
    return fig


def plot_bb_squeeze_demo() -> go.Figure:
    n = 55
    idx = pd.date_range("2024-04-01", periods=n, freq="D")
    rng = np.random.default_rng(2)
    close = np.concatenate([
        100 + rng.normal(0, 0.3, 35),
        np.linspace(100, 108, 20) + rng.normal(0, 0.4, 20),
    ])
    break_up_i = 38
    break_dn_i = 48
    close[40:45] = np.linspace(108, 100, 5)
    close[45:50] = 100 + rng.normal(0, 0.2, 5)
    mid = pd.Series(close).rolling(20).mean().bfill()
    std = pd.Series(close).rolling(20).std().bfill()
    upper = mid + 2 * std
    lower = mid - 2 * std

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=idx, y=close, name="終値", line=dict(color="#e2e8f0", width=2)))
    fig.add_trace(go.Scatter(x=idx, y=upper, name="BB 上限", line=dict(color="#94a3b8", width=1, dash="dot")))
    fig.add_trace(go.Scatter(x=idx, y=lower, name="BB 下限", line=dict(color="#94a3b8", width=1, dash="dot"), fill="tonexty", fillcolor="rgba(148,163,184,0.08)"))
    fig.add_trace(go.Scatter(x=idx, y=mid, name="BB 中心", line=dict(color="#64748b", width=1)))

    fig.add_vrect(x0=idx[25], x1=idx[37], fillcolor=C_ZONE_WARN, line_width=0, annotation_text="① スクイーズ", annotation_position="top left")

    fig.add_trace(
        go.Scatter(
            x=[idx[break_up_i]],
            y=[close[break_up_i]],
            mode="markers+text",
            text=["買い"],
            textposition="top center",
            marker=dict(symbol="triangle-up", size=16, color=C_ENTRY, line=dict(width=2, color="white")),
            name="🟢 買い（上限ブレイク）",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[idx[break_dn_i]],
            y=[close[break_dn_i]],
            mode="markers+text",
            text=["売り"],
            textposition="bottom center",
            marker=dict(symbol="triangle-down", size=16, color=C_SHORT, line=dict(width=2, color="white")),
            name="🔴 売り（下限ブレイク）",
        )
    )
    _annotate(fig, idx[break_up_i], close[break_up_i], "上限ブレイク", ax=45, ay=-40, color=C_ENTRY)
    _annotate(fig, idx[break_dn_i], close[break_dn_i], "下限ブレイク", ax=45, ay=40, color=C_SHORT)
    _base_layout(fig, "BB スクイーズ — 買い/売りシグナル")
    return fig


def plot_vwap_ema_demo() -> go.Figure:
    n = 60
    idx = pd.date_range("2024-07-01 09:30", periods=n, freq="5min")
    t = np.arange(n)
    vwap = 130 + 0.01 * t
    close = vwap + 0.2 * np.sin(t / 4)
    close[28:38] += 0.4
    close[45:] -= 0.5
    ema9 = pd.Series(close).ewm(span=9).mean().values
    ema21 = pd.Series(close).ewm(span=21).mean().values

    long_i = 32
    short_i = 50
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=idx, y=close, name="終値（5分足）", line=dict(color="#e2e8f0", width=2)))
    fig.add_trace(go.Scatter(x=idx, y=vwap, name="VWAP（基準線）", line=dict(color=C_VWAP, width=2.5)))
    fig.add_trace(go.Scatter(x=idx, y=ema9, name="EMA9", line=dict(color="#22c55e", width=1.5)))
    fig.add_trace(go.Scatter(x=idx, y=ema21, name="EMA21", line=dict(color="#f97316", width=1.5)))

    fig.add_hrect(y0=vwap[long_i] - 0.05, y1=vwap[long_i] + 3, fillcolor="rgba(34,197,94,0.1)", line_width=0, annotation_text="🟢 終値>VWAP", annotation_position="left")
    fig.add_hrect(y0=vwap[short_i] - 3, y1=vwap[short_i] + 0.05, fillcolor="rgba(239,68,68,0.1)", line_width=0, annotation_text="🔴 終値<VWAP", annotation_position="left")

    fig.add_trace(
        go.Scatter(
            x=[idx[long_i]], y=[close[long_i]], mode="markers+text", text=["買い"], textposition="top center",
            marker=dict(symbol="triangle-up", size=16, color=C_ENTRY, line=dict(width=2, color="white")),
            name="🟢 買いシグナル",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[idx[short_i]], y=[close[short_i]], mode="markers+text", text=["売り"], textposition="bottom center",
            marker=dict(symbol="triangle-down", size=16, color=C_SHORT, line=dict(width=2, color="white")),
            name="🔴 売りシグナル",
        )
    )
    _annotate(fig, idx[long_i], ema9[long_i], "EMA9↑21", ax=-55, ay=35, color=C_ENTRY)
    _annotate(fig, idx[short_i], ema9[short_i], "EMA9↓21", ax=-55, ay=-35, color=C_SHORT)
    _base_layout(fig, "VWAP + EMA — 買い/売りシグナル")
    return fig


def plot_vwap_reclaim_demo() -> go.Figure:
    n = 50
    idx = pd.date_range("2024-07-02 10:00", periods=n, freq="5min")
    vwap = np.full(n, 128.0)
    close = vwap.copy()
    close[:15] -= np.linspace(0, 0.8, 15)
    close[15:22] += np.linspace(0, 0.55, 7)
    close[22:35] = close[21]
    close[35:] += np.linspace(0, 0.9, n - 35)

    long_stretch_i = 14
    long_entry_i = 20
    short_stretch_i = 38
    short_entry_i = 44

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=idx, y=close, name="終値", line=dict(color="#e2e8f0", width=2)))
    fig.add_trace(go.Scatter(x=idx, y=vwap, name="VWAP", line=dict(color=C_VWAP, width=2.5)))

    fig.add_trace(
        go.Scatter(x=[idx[long_entry_i]], y=[close[long_entry_i]], mode="markers+text", text=["買い"], textposition="top center",
            marker=dict(symbol="triangle-up", size=16, color=C_ENTRY, line=dict(width=2, color="white")), name="🟢 買い（下ストレッチ→戻り）")
    )
    fig.add_trace(
        go.Scatter(x=[idx[short_entry_i]], y=[close[short_entry_i]], mode="markers+text", text=["売り"], textposition="bottom center",
            marker=dict(symbol="triangle-down", size=16, color=C_SHORT, line=dict(width=2, color="white")), name="🔴 売り（上ストレッチ→戻り）")
    )
    _annotate(fig, idx[long_stretch_i], close[long_stretch_i], "下ストレッチ", ax=-50, ay=30, color=C_SIGNAL)
    _annotate(fig, idx[short_stretch_i], close[short_stretch_i], "上ストレッチ", ax=-50, ay=-30, color=C_SIGNAL)
    _base_layout(fig, "VWAP リクレイム — 買い/売りシグナル")
    return fig


def plot_orb_demo() -> go.Figure:
    n = 36
    idx = pd.date_range("2024-07-03 09:30", periods=n, freq="5min")
    or_bars = 4
    or_high = 135.5
    or_low = 134.2
    close = np.full(n, 134.8)
    close[or_bars:] = np.linspace(134.9, 137.2, n - or_bars) + np.random.default_rng(4).normal(0, 0.08, n - or_bars)

    break_up_i = or_bars + 3
    break_dn_i = or_bars + 12
    close[break_dn_i - 1 : break_dn_i + 2] = [or_low - 0.1, or_low - 0.25, or_low - 0.15]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=idx, y=close, name="終値", line=dict(color="#e2e8f0", width=2)))

    fig.add_hrect(y0=or_low, y1=or_high, fillcolor=C_ZONE, line_width=1, line_color="#3b82f6", annotation_text="Opening Range", annotation_position="top left")
    fig.add_hline(y=or_high, line_dash="dash", line_color=C_ENTRY, annotation_text="OR 高値", annotation_position="right")
    fig.add_hline(y=or_low, line_dash="dash", line_color=C_SHORT, annotation_text="OR 安値", annotation_position="right")

    fig.add_trace(
        go.Scatter(x=[idx[break_up_i]], y=[close[break_up_i]], mode="markers+text", text=["買い"], textposition="top center",
            marker=dict(symbol="triangle-up", size=16, color=C_ENTRY, line=dict(width=2, color="white")), name="🟢 買い（OR高値ブレイク）")
    )
    fig.add_trace(
        go.Scatter(x=[idx[break_dn_i]], y=[close[break_dn_i]], mode="markers+text", text=["売り"], textposition="bottom center",
            marker=dict(symbol="triangle-down", size=16, color=C_SHORT, line=dict(width=2, color="white")), name="🔴 売り（OR安値ブレイク）")
    )
    _annotate(fig, idx[break_up_i], close[break_up_i], "高値ブレイク", ax=45, ay=-40, color=C_ENTRY)
    _annotate(fig, idx[break_dn_i], close[break_dn_i], "安値ブレイク", ax=45, ay=40, color=C_SHORT)
    _base_layout(fig, "ORB — 買い/売りシグナル")
    return fig


VISUAL_CHECKS_LONG: dict[str, list[tuple[str, str, str]]] = {
    "macd_cross": [
        ("①", "トレンド", "終値 > EMA50/200"),
        ("②", "GC", "MACD がシグナルを下から上へクロス"),
        ("③", "フィルタ", "ADX > 23 など"),
    ],
    "ema_pullback": [
        ("①", "大局", "終値 > EMA200"),
        ("②", "押し目", "安値が EMA20 付近"),
        ("③", "反発", "終値 > EMA20"),
    ],
    "bb_squeeze": [
        ("①", "スクイーズ", "BB 幅が狭い"),
        ("②", "ブレイク", "上限を終値で上抜け"),
    ],
    "vwap_ema": [
        ("①", "方向", "終値 > VWAP"),
        ("②", "クロス", "EMA9 が EMA21 を上抜け"),
        ("③", "出来高", "平均の 1.5 倍以上"),
    ],
    "vwap_reclaim": [
        ("①", "ストレッチ", "VWAP より −0.5% 以下"),
        ("②", "リクレイム", "VWAP 方向へ戻り始める"),
    ],
    "orb": [
        ("①", "OR", "寄り付き20分の高値"),
        ("②", "ブレイク", "OR 高値を終値で上抜け"),
    ],
}

VISUAL_CHECKS_SHORT: dict[str, list[tuple[str, str, str]] | None] = {
    "macd_cross": [
        ("①", "トレンド", "終値 < EMA50/200"),
        ("②", "DC", "MACD がシグナルを上から下へクロス"),
        ("③", "条件", "long_only=false のときのみ"),
    ],
    "ema_pullback": None,
    "bb_squeeze": [
        ("①", "スクイーズ", "BB 幅が狭い"),
        ("②", "ブレイク", "下限を終値で下抜け"),
    ],
    "vwap_ema": [
        ("①", "方向", "終値 < VWAP"),
        ("②", "クロス", "EMA9 が EMA21 を下抜け"),
        ("③", "出来高", "平均の 1.5 倍以上"),
    ],
    "vwap_reclaim": [
        ("①", "ストレッチ", "VWAP より +0.5% 以上"),
        ("②", "リクレイム", "VWAP 方向へ戻り始める"),
    ],
    "orb": [
        ("①", "OR", "寄り付き20分の安値"),
        ("②", "ブレイク", "OR 安値を終値で下抜け"),
    ],
}

# backward compat alias
VISUAL_CHECKS = VISUAL_CHECKS_LONG

PLOT_FNS = {
    "macd_cross": plot_macd_cross_demo,
    "ema_pullback": plot_ema_pullback_demo,
    "bb_squeeze": plot_bb_squeeze_demo,
    "vwap_ema": plot_vwap_ema_demo,
    "vwap_reclaim": plot_vwap_reclaim_demo,
    "orb": plot_orb_demo,
}


def plot_strategy_demo(strategy_key: str) -> go.Figure | None:
    fn = PLOT_FNS.get(strategy_key)
    return fn() if fn else None


def _render_check_row(checks: list[tuple[str, str, str]], accent: str) -> None:
    import streamlit as st

    cols = st.columns(len(checks))
    for i, (num, title, desc) in enumerate(checks):
        with cols[i]:
            st.markdown(
                f"<div style='background:{accent}22;border-left:4px solid {accent};"
                f"padding:8px 12px;border-radius:4px;margin-bottom:8px'>"
                f"<b>{num} {title}</b><br><span style='font-size:0.85em;color:#94a3b8'>{desc}</span></div>",
                unsafe_allow_html=True,
            )


def render_check_legend(strategy_key: str) -> None:
    """Colored buy/sell checklists matching chart markers."""
    import streamlit as st

    long_checks = VISUAL_CHECKS_LONG.get(strategy_key, [])
    short_checks = VISUAL_CHECKS_SHORT.get(strategy_key)

    lc1, lc2 = st.columns(2)
    with lc1:
        st.markdown("**🟢 買いシグナルの条件**")
        if long_checks:
            _render_check_row(long_checks, C_ENTRY)
        else:
            st.caption("—")
    with lc2:
        st.markdown("**🔴 売りシグナルの条件**")
        if short_checks:
            _render_check_row(short_checks, C_SHORT)
        else:
            st.info("この戦略は **ロング（買い）専用** — 売りシグナルは出ません。")
