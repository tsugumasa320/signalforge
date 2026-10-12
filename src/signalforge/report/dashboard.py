"""SignalForge — Interactive analysis dashboard (Streamlit)."""

from __future__ import annotations

import os

os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

from signalforge.bootstrap import warmup_native_libs

warmup_native_libs()

import json
import warnings
from typing import Any

import pandas as pd
import streamlit as st

from signalforge.config import data_dir, load_style_config
from signalforge.optimize.champion import CHAMPION_MACD_PARAMS, champion_cfg_override
from signalforge.optimize.spaces import strategies_for_style
from signalforge.pipeline import run_backtest_pipeline
from signalforge.report.charts import (
    plot_cost_breakdown,
    plot_cumulative_pnl,
    plot_equity_and_drawdown,
    plot_oos_comparison,
    plot_price_and_trades,
    plot_trade_pnl,
)
from signalforge.report.dashboard_components import (
    oos_metrics_from_trades,
    render_cost_row,
    render_metric_row,
    render_verdict_panel,
    trades_dataframe,
    verdict_badge,
)
from signalforge.report.dashboard_glossary import (
    STRATEGY_DESCRIPTIONS,
    STYLE_DESCRIPTIONS,
    TAB_INTROS,
    render_glossary_tab,
    render_tab_intro,
)
from signalforge.report.dashboard_strategies import render_strategies_tab
from signalforge.config import load_market_config
from signalforge.report.dashboard_explorer import _cfg_override, _default_dates, render_explorer_tab
from signalforge.report.dashboard_view import (
    render_results_home,
    render_results_sidebar,
    render_strategy_detail,
)

MACD_OPTIMIZED = CHAMPION_MACD_PARAMS  # backward compat for sidebar toggle label

COST_LABELS = {
    "japan": "日本株（手数料・スリッページ）",
    "legacy": "Legacy（簡易）",
    "alpaca": "Alpaca（公式料金表）",
    "alpaca_conservative": "Alpaca 保守（広スプレッド）",
}

STYLE_LABELS = {
    "swing": "スイング（日足）",
    "swing_champion": "🏆 Champion（最強プリセット）",
    "swing_high_winrate": "スイング・高勝率",
    "daytrade": "デイトレ（5分足）",
}


def _plotly(fig, key: str) -> None:
    st.plotly_chart(fig, width="stretch", key=key)


def _init_session() -> None:
    defaults = {
        "result": None,
        "compare_rows": [],
        "verify_rows": [],
        "last_error": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


@st.cache_data(show_spinner=False, ttl=300)
def _run_backtest(
    style: str,
    strategy: str,
    ml_filter: bool,
    cost_model: str,
    use_macd_opt: bool,
    ticker: str,
    start_iso: str | None,
    end_iso: str | None,
) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=PendingDeprecationWarning)
        cfg_override: dict[str, Any] | None = None
        if strategy == "macd_cross" and use_macd_opt:
            cfg_override = champion_cfg_override(style, strategy, load_style_config(style))
        from datetime import date

        start_d = date.fromisoformat(start_iso) if start_iso else None
        end_d = date.fromisoformat(end_iso) if end_iso else None
        window = _cfg_override(ticker or None, start_d, end_d)
        if window:
            base = dict(cfg_override or {})
            for key, val in window.items():
                if key == "backtest" and isinstance(val, dict):
                    base["backtest"] = {**base.get("backtest", {}), **val}
                else:
                    base[key] = val
            cfg_override = base
        return run_backtest_pipeline(
            style,
            strategy,
            ml_filter=ml_filter,
            cost_model=cost_model,
            cfg_override=cfg_override,
        )


def _load_journal(run_id: str) -> dict[str, Any]:
    path = data_dir() / "reports" / f"journal_{run_id}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _render_inline_backtest() -> None:
    """Single-strategy backtest controls (main panel, not sidebar)."""
    st.subheader("単一戦略を再実行")
    c1, c2, c3 = st.columns(3)
    with c1:
        style = st.selectbox(
            "スタイル",
            ["swing", "swing_champion", "daytrade"],
            format_func=lambda x: STYLE_LABELS.get(x, x),
            key="adv_style",
        )
    with c2:
        strategies = list(strategies_for_style(style))
        default_strategy = "macd_cross" if style.startswith("swing") else "vwap_ema"
        strategy = st.selectbox(
            "戦略",
            strategies,
            index=strategies.index(default_strategy) if default_strategy in strategies else 0,
            key="adv_strategy",
        )
    with c3:
        cost_model = st.selectbox(
            "コスト",
            ["japan", "legacy", "alpaca"],
            format_func=lambda x: COST_LABELS.get(x, x),
            key="adv_cost",
        )
    ml_filter = st.toggle("ML フィルタ", value=style == "swing_champion", key="adv_ml")
    default_start, _ = _default_dates()
    r1, r2, r3 = st.columns(3)
    with r1:
        bt_ticker = st.text_input(
            "銘柄",
            value=str(load_market_config("japan").get("default_ticker", "7203.T")),
            key="adv_ticker",
        )
    with r2:
        bt_start = st.date_input("開始日", value=default_start, key="adv_start")
    with r3:
        use_end = st.checkbox("終了日", value=False, key="adv_use_end")
        bt_end = st.date_input("終了日", value=default_start, disabled=not use_end, key="adv_end")
    use_macd_opt = strategy == "macd_cross" and style != "swing_champion"
    if use_macd_opt:
        use_macd_opt = st.toggle("macd_cross 最適化", value=True, key="adv_macd_opt")

    if st.button("バックテスト実行", type="primary", key="adv_run"):
        with st.spinner("実行中…"):
            try:
                st.session_state.result = _run_backtest(
                    style,
                    strategy,
                    ml_filter,
                    cost_model,
                    use_macd_opt,
                    bt_ticker.strip(),
                    bt_start.isoformat(),
                    bt_end.isoformat() if use_end else None,
                )
                st.session_state.last_error = None
            except Exception as exc:
                st.session_state.last_error = str(exc)

    if st.session_state.last_error:
        st.error(st.session_state.last_error)
    result = st.session_state.result
    if result:
        cfg = {"ml_filter": ml_filter, "cost_model": cost_model}
        _page_overview(result, cfg)
        _page_charts(result)
        with st.expander("トレード一覧"):
            _page_trades(result, None)


def _page_overview(result: dict[str, Any], cfg: dict[str, Any]) -> None:
    title, body = TAB_INTROS["overview"]
    render_tab_intro(title, body)

    metrics = result["metrics"]
    trades = result["trades"]
    oos_m = oos_metrics_from_trades(trades, result["equity"]) if cfg["ml_filter"] else {}

    st.subheader("📊 パフォーマンス概要")
    render_verdict_panel(metrics, COST_LABELS.get(cfg["cost_model"], cfg["cost_model"]))
    render_metric_row(metrics)
    st.caption(
        f"総リターン: **{metrics.get('total_return_pct', 0):.1f}%**  |  "
        f"Gross PF（コスト前）: **{metrics.get('gross_profit_factor', metrics.get('profit_factor', 0)):.2f}**"
    )
    render_cost_row(metrics)

    if cfg["ml_filter"] and oos_m.get("total_trades", 0) > 0:
        st.subheader("🎯 OOS（未学習期間・Walk-Forward ML）")
        st.caption("OOS = モデルが学習していない期間の成績。こちらが実運用に近い指標です。")
        render_metric_row(oos_m, prefix="OOS ")
        oos_label, _ = verdict_badge(oos_m.get("profit_factor", 0), oos_m.get("total_return_pct", 0))
        st.info(f"OOS 判定: {oos_label}  |  OOS 勝率: **{oos_m.get('win_rate', 0):.1%}**")

    c1, c2 = st.columns(2)
    with c1:
        _plotly(plot_equity_and_drawdown(result["equity"], "資産曲線 & ドローダウン"), "chart_equity")
    with c2:
        if cfg["ml_filter"] and oos_m.get("total_trades", 0) > 0:
            _plotly(plot_oos_comparison(metrics, oos_m), "chart_oos_cmp")
        else:
            _plotly(plot_cost_breakdown(trades), "chart_cost_overview")


def _page_charts(result: dict[str, Any]) -> None:
    title, body = TAB_INTROS["charts"]
    render_tab_intro(title, body)

    df = result["df"]
    trades = result["trades"]
    _plotly(
        plot_price_and_trades(df, trades, title=f"{result['strategy']} — 価格 & エントリー/イグジット"),
        "chart_price",
    )
    c1, c2 = st.columns(2)
    with c1:
        _plotly(plot_trade_pnl(trades, "取引別 PnL"), "chart_pnl_bars")
    with c2:
        _plotly(plot_cumulative_pnl(trades, "累積 PnL"), "chart_pnl_cum")


def _page_trades(result: dict[str, Any] | None, saved_run: str | None) -> None:
    title, body = TAB_INTROS["trades"]
    render_tab_intro(title, body)

    st.subheader("📋 トレード詳細")

    if result is not None:
        trades = result["trades"].copy()
        st.caption(f"Run ID: {result.get('run_id', '—')}  |  {result.get('strategy')} / {result.get('style')}")
    elif saved_run:
        data = _load_journal(saved_run)
        trades_list = data.get("trades", [])
        trades = pd.DataFrame(trades_list) if trades_list else pd.DataFrame()
        if not trades.empty and "timestamp" in trades.columns:
            trades = trades.rename(columns={"timestamp": "entry_time"})
        st.caption(f"保存済み Run ID: {saved_run}")
    else:
        st.info("バックテストを実行するか、保存済みジャーナルを選択してください。")
        return

    if trades.empty:
        st.warning("取引がありません。")
        return

    show_oos = st.checkbox(
        "OOS トレードのみ表示",
        value=False,
        key="filter_oos",
        help="ML フィルタ使用時、モデルが学習していない期間の取引だけに絞り込む",
    )
    if show_oos and "is_oos" in trades.columns:
        if trades["is_oos"].dtype == bool:
            trades = trades[trades["is_oos"]]
        else:
            trades = trades[trades["is_oos"].isin([True, "OOS", "True"])]

    st.dataframe(trades_dataframe(trades), width="stretch", hide_index=True, key="df_trades")

    st.subheader("取引の解説")
    for idx, row in trades.head(20).iterrows():
        tag = " [OOS]" if row.get("is_oos") in (True, "OOS") else ""
        pnl = row.get("pnl_pct")
        pnl_val = float(pnl) if pd.notna(pnl) else 0.0
        icon = "🟢" if pnl_val > 0 else "🔴"
        entry_ts = row.get("entry_time", row.get("timestamp", ""))
        with st.expander(f"{icon} {entry_ts}{tag} — 損益 {pnl_val:+.2f}%"):
            st.write(
                f"**方向:** {row.get('side', row.get('action', '—'))}  |  "
                f"**保有:** {row.get('hold_bars', '—')} 本（足）  |  "
                f"**決済理由:** {row.get('reason', '—')}"
            )
            cost = row.get("total_cost_usd")
            if pd.notna(cost) and cost:
                st.write(
                    f"**取引コスト:** ${float(cost):.2f} "
                    f"（規制費 ${float(row.get('total_fees_usd', 0) or 0):.2f} + "
                    f"スリッページ ${float(row.get('total_slippage_usd', 0) or 0):.2f}）"
                )


def run_dashboard() -> None:
    st.set_page_config(
        page_title="SignalForge",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    pick = render_results_sidebar()

    st.title("SignalForge")
    st.caption("日本株 — **TSE 実験・事前バックテスト** の閲覧。実行中も完了分が表示されます。")

    tab_results, tab_guide, tab_glossary, tab_advanced = st.tabs(
        ["📊 戦略結果", "📚 戦略解説", "📖 用語集", "⚙️ 上級者（再実行）"]
    )

    with tab_results:
        render_results_home()
        if pick and pick != "（一覧のみ）":
            st.divider()
            render_strategy_detail(pick)

    with tab_guide:
        render_strategies_tab()

    with tab_glossary:
        render_glossary_tab()

    with tab_advanced:
        st.caption("条件を変えてその場で BT する場合のみ。通常は **戦略結果** タブで十分です。")
        _init_session()
        _render_inline_backtest()
        with st.expander("条件を変えて一括再実行", expanded=True):
            render_explorer_tab(advanced=True)


if __name__ == "__main__":
    run_dashboard()
