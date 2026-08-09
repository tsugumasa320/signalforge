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
    plot_cost_comparison,
    plot_cumulative_pnl,
    plot_equity_and_drawdown,
    plot_oos_comparison,
    plot_price_and_trades,
    plot_strategy_comparison,
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
    SIDEBAR_HELP,
    STRATEGY_DESCRIPTIONS,
    STYLE_DESCRIPTIONS,
    TAB_INTROS,
    render_glossary_tab,
    render_sidebar_glossary_link,
    render_tab_intro,
)
from signalforge.report.dashboard_strategies import render_strategies_tab

MACD_OPTIMIZED = CHAMPION_MACD_PARAMS  # backward compat for sidebar toggle label

COST_LABELS = {
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
) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=PendingDeprecationWarning)
        cfg_override = None
        if strategy == "macd_cross" and use_macd_opt:
            cfg_override = champion_cfg_override(style, strategy, load_style_config(style))
        return run_backtest_pipeline(
            style,
            strategy,
            ml_filter=ml_filter,
            cost_model=cost_model,
            cfg_override=cfg_override,
        )


@st.cache_data(show_spinner=False, ttl=300)
def _compare_strategies(style: str, ml_filter: bool, cost_model: str) -> list[dict[str, Any]]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=PendingDeprecationWarning)
        rows = []
        for name in strategies_for_style(style):
            use_opt = name == "macd_cross"
            result = _run_backtest(style, name, ml_filter, cost_model, use_opt)
            trades = result["trades"]
            if ml_filter and not trades.empty and "is_oos" in trades.columns:
                m = oos_metrics_from_trades(trades, result["equity"])
                scope = "OOS"
            else:
                m = result["metrics"]
                scope = "全期間"
            rows.append(
                {
                    "strategy": name,
                    "scope": scope,
                    "profit_factor": m.get("profit_factor", 0),
                    "win_rate": m.get("win_rate", 0),
                    "sharpe": m.get("sharpe", 0),
                    "total_trades": m.get("total_trades", 0),
                    "max_drawdown_pct": m.get("max_drawdown_pct", 0),
                    "total_return_pct": m.get("total_return_pct", 0),
                    "total_cost_usd": m.get("total_cost_usd", 0),
                }
            )
        return rows


@st.cache_data(show_spinner=False, ttl=300)
def _verify_costs(style: str, strategy: str, ml_filter: bool, use_macd_opt: bool) -> list[dict[str, Any]]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=PendingDeprecationWarning)
        rows = []
        for preset in ("legacy", "alpaca", "alpaca_conservative"):
            cfg_override = None
            if strategy == "macd_cross" and use_macd_opt:
                cfg_override = champion_cfg_override(style, strategy, load_style_config(style))
            result = run_backtest_pipeline(
                style,
                strategy,
                ml_filter=ml_filter,
                cost_model=preset,
                cfg_override=cfg_override,
            )
            trades = result["trades"]
            if ml_filter and not trades.empty and "is_oos" in trades.columns:
                m = oos_metrics_from_trades(trades, result["equity"])
            else:
                m = result["metrics"]
            label, _ = verdict_badge(m.get("profit_factor", 0), m.get("total_return_pct", 0))
            rows.append(
                {
                    "cost_model": COST_LABELS.get(preset, preset),
                    "preset": preset,
                    "profit_factor": m.get("profit_factor", 0),
                    "total_return_pct": m.get("total_return_pct", 0),
                    "total_trades": m.get("total_trades", 0),
                    "total_cost_usd": m.get("total_cost_usd", 0),
                    "verdict": label,
                }
            )
        return rows


def _load_journal(run_id: str) -> dict[str, Any]:
    path = data_dir() / "reports" / f"journal_{run_id}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sidebar() -> dict[str, Any]:
    st.sidebar.header("⚙️ 設定")
    style = st.sidebar.selectbox(
        "スタイル",
        ["swing", "swing_champion", "swing_high_winrate", "daytrade"],
        format_func=lambda x: STYLE_LABELS.get(x, x),
        help=SIDEBAR_HELP["style"],
    )
    st.sidebar.caption(STYLE_DESCRIPTIONS.get(style, ""))
    strategies = list(strategies_for_style(style))
    default_strategy = "macd_cross" if style.startswith("swing") else "vwap_ema"
    strategy = st.sidebar.selectbox(
        "戦略",
        strategies,
        index=strategies.index(default_strategy) if default_strategy in strategies else 0,
        help=SIDEBAR_HELP["strategy"],
    )
    st.sidebar.caption(STRATEGY_DESCRIPTIONS.get(strategy, ""))
    ml_filter = st.sidebar.toggle(
        "ML フィルタ（Walk-Forward OOS）",
        value=(style in ("swing_champion", "swing_high_winrate")),
        help=SIDEBAR_HELP["ml_filter"],
    )
    cost_model = st.sidebar.selectbox(
        "コストモデル",
        ["alpaca", "legacy", "alpaca_conservative"],
        format_func=lambda x: COST_LABELS.get(x, x),
        help=SIDEBAR_HELP["cost_model"],
    )
    use_macd_opt = False
    if strategy == "macd_cross" and style not in ("swing_champion", "swing_high_winrate"):
        use_macd_opt = st.sidebar.toggle(
            "macd_cross 最適化パラメータ",
            value=True,
            help=SIDEBAR_HELP["macd_opt"],
        )
        if use_macd_opt:
            st.sidebar.caption("ADX>23, EMA200, 利確=2.0×ATR, 損切=1.5×ATR")

    st.sidebar.divider()
    st.sidebar.subheader("▶ 実行")

    if st.sidebar.button(
        "バックテスト実行",
        type="primary",
        width="stretch",
        key="btn_backtest",
        help=SIDEBAR_HELP["backtest"],
    ):
        with st.spinner("バックテスト実行中..."):
            try:
                st.session_state.result = _run_backtest(style, strategy, ml_filter, cost_model, use_macd_opt)
                st.session_state.last_error = None
            except Exception as exc:
                st.session_state.last_error = str(exc)

    if st.sidebar.button(
        "全戦略を比較",
        width="stretch",
        key="btn_compare",
        help=SIDEBAR_HELP["compare"],
    ):
        with st.spinner("全戦略を評価中..."):
            try:
                st.session_state.compare_rows = _compare_strategies(style, ml_filter, cost_model)
                st.session_state.last_error = None
            except Exception as exc:
                st.session_state.last_error = str(exc)

    if st.sidebar.button(
        "コスト検証（3モデル）",
        width="stretch",
        key="btn_verify",
        help=SIDEBAR_HELP["verify_costs"],
    ):
        with st.spinner("コストモデル検証中..."):
            try:
                st.session_state.verify_rows = _verify_costs(style, strategy, ml_filter, use_macd_opt)
                st.session_state.last_error = None
            except Exception as exc:
                st.session_state.last_error = str(exc)

    st.sidebar.divider()
    st.sidebar.caption(
        "Alpaca 想定: 株式手数料 $0 + SEC/TAF/CAT 規制費 + スリッページ（詳細は「コスト」タブ）"
    )
    render_sidebar_glossary_link()

    reports_dir = data_dir() / "reports"
    reports_dir.mkdir(exist_ok=True)
    journals = sorted(reports_dir.glob("journal_*.json"))
    saved_run = None
    if journals:
        saved_run = st.sidebar.selectbox(
            "保存済みジャーナル",
            ["（なし）"] + [p.stem.replace("journal_", "") for p in journals],
            key="saved_journal",
        )

    return {
        "style": style,
        "strategy": strategy,
        "ml_filter": ml_filter,
        "cost_model": cost_model,
        "use_macd_opt": use_macd_opt,
        "saved_run": saved_run if saved_run != "（なし）" else None,
    }


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


def _page_compare(rows: list[dict[str, Any]]) -> None:
    title, body = TAB_INTROS["compare"]
    render_tab_intro(title, body)

    if not rows:
        st.info("サイドバーの「全戦略を比較」を実行してください。")
        return

    st.subheader("📈 戦略比較")
    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        key="df_compare",
        column_config={
            "strategy": st.column_config.TextColumn("戦略"),
            "scope": st.column_config.TextColumn("評価範囲", help="OOS = 未学習期間、全期間 = データ全体"),
            "profit_factor": st.column_config.NumberColumn("損益比(PF)", format="%.2f"),
            "win_rate": st.column_config.NumberColumn("Win率", format="%.1%%"),
            "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
            "total_trades": st.column_config.NumberColumn("取引数"),
            "max_drawdown_pct": st.column_config.NumberColumn("Max DD %", format="%.1f"),
            "total_return_pct": st.column_config.NumberColumn("総リターン %", format="%.1f"),
            "total_cost_usd": st.column_config.NumberColumn("コスト($)", format="$%.0f"),
        },
    )
    _plotly(plot_strategy_comparison(rows, "profit_factor"), "chart_strategy_cmp")

    best = max(rows, key=lambda r: r["profit_factor"])
    label, level = verdict_badge(best["profit_factor"], best["total_return_pct"])
    if level == "success":
        st.success(f"最良: **{best['strategy']}** ({best['scope']}) — PF {best['profit_factor']:.2f} {label}")
    elif level == "warning":
        st.warning(f"最良: **{best['strategy']}** ({best['scope']}) — PF {best['profit_factor']:.2f} {label}")
    else:
        st.error(f"最良: **{best['strategy']}** ({best['scope']}) — PF {best['profit_factor']:.2f} {label}")


def _page_costs(verify_rows: list[dict[str, Any]], result: dict[str, Any] | None) -> None:
    title, body = TAB_INTROS["costs"]
    render_tab_intro(title, body)

    st.subheader("💰 コスト分析")
    st.markdown(
        """
**Alpaca（API 経由・米国株）の実コスト構成**

| 項目 | 金額 | タイミング |
|------|------|-----------|
| 手数料 | **$0** | — |
| SEC 規制費 | $0.0000206 × 売却代金 | 売りのみ |
| FINRA TAF | $0.000195/株（上限 $9.79） | 売りのみ |
| FINRA CAT | $0.000003/株 | 買い・売り |
| スリッページ | 設定 bps（寄付/バー始値） | 約定時 |

※ 規制費用は $0.01 単位で切り上げ。コストの大半は **スリッページ** です。
        """
    )

    if verify_rows:
        _plotly(plot_cost_comparison(verify_rows), "chart_cost_cmp")
        st.dataframe(pd.DataFrame(verify_rows), width="stretch", hide_index=True, key="df_verify")
    else:
        st.info("サイドバーの「コスト検証（3モデル）」を実行してください。")

    if result is not None and not result["trades"].empty:
        _plotly(plot_cost_breakdown(result["trades"]), "chart_cost_breakdown")


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


def _page_ml(result: dict[str, Any] | None, saved_run: str | None) -> None:
    title, body = TAB_INTROS["ml"]
    render_tab_intro(title, body)

    st.subheader("🤖 ML 説明 & 拒否シグナル")

    run_id = result.get("run_id") if result is not None else saved_run
    if not run_id:
        st.info("バックテストを実行するか、保存済みジャーナルを選択してください。")
        return

    path = data_dir() / "reports" / f"journal_{run_id}.json"
    if not path.exists():
        st.warning(f"ジャーナルが見つかりません: {path}")
        return

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    journal_trades = data.get("trades", [])
    rejected = data.get("rejected", [])

    st.markdown("#### ML が採用した取引の SHAP 説明")
    st.caption("SHAP: 各テクニカル指標が「この取引を採用した理由」にどれだけ寄与したか。🟩=プラス要因、🟥=マイナス要因。")
    ml_trades = [t for t in journal_trades if t.get("ml_explanation")]
    if not ml_trades:
        st.caption("ML 説明付きトレードなし（ML フィルタ OFF、または ML 未学習）")
    for t in ml_trades[:15]:
        ml = t.get("ml_explanation") or {}
        st.markdown(f"**Trade #{t.get('trade_id', '?')}** — {t.get('summary_ja', '')}")
        for feat in ml.get("top_features") or []:
            shap_val = float(feat.get("shap") or 0)
            bar = "🟩" * min(int(abs(shap_val) * 10), 5) if shap_val > 0 else "🟥" * min(int(abs(shap_val) * 10), 5)
            desc = feat.get("desc") or ""
            st.write(
                f"{bar} `{feat.get('name', '?')}` = {float(feat.get('value', 0)):.3f} "
                f"(SHAP {shap_val:+.3f}) — {desc}"
            )

    st.markdown("#### ML が拒否したシグナル")
    st.caption("テクニカルでは買いシグナルが出たが、ML が「勝率が低そう」と判断して見送った場面。")
    if not rejected:
        st.caption("拒否シグナルなし")
    for r in rejected[:30]:
        tag = " [OOS]" if r.get("is_oos") else ""
        st.write(f"- `{r.get('timestamp')}`{tag}: {r.get('summary_ja', '')}")


def run_dashboard() -> None:
    st.set_page_config(
        page_title="SignalForge",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _init_session()
    cfg = _sidebar()

    st.title("SignalForge")
    st.caption(
        "NVDA テクニカル分析 — バックテスト・ML・Alpaca 実コスト検証。"
        "わからない用語は **📖 用語集**、各戦略の詳細は **📚 戦略解説** タブを参照。"
    )

    if st.session_state.last_error:
        st.error(f"エラー: {st.session_state.last_error}")

    result = st.session_state.result
    if result:
        meta = (
            f"**{result['strategy']}** / {result['style']}  |  "
            f"データ: {result.get('data_source', '?')}  |  "
            f"コスト: {COST_LABELS.get(cfg['cost_model'], cfg['cost_model'])}"
        )
        if result.get("backtest_window"):
            meta += f"  |  期間: {result['backtest_window']}"
        mr = result.get("ml_report", {})
        if mr.get("trained"):
            avg_acc = mr.get("avg_oos_accuracy")
            acc_txt = f"{avg_acc:.1%}" if avg_acc is not None else "—"
            meta += f"  |  ML folds: {mr.get('folds', 0)}, OOS accuracy: {acc_txt}"
        st.markdown(meta)

    tab_overview, tab_charts, tab_compare, tab_cost, tab_trades, tab_ml, tab_strategies, tab_glossary = st.tabs(
        ["📊 概要", "📈 チャート", "⚖️ 戦略比較", "💰 コスト", "📋 トレード", "🤖 ML/監査", "📚 戦略解説", "📖 用語集"]
    )

    with tab_overview:
        if result:
            _page_overview(result, cfg)
        else:
            st.info("👈 サイドバーから **バックテスト実行** をクリックしてください。")
            st.markdown(
                "**初めての方へ:** まず「スタイル」と「戦略」を選び、**バックテスト実行** で過去データでの"
                "シミュレーション結果を表示します。用語がわからない場合は **📖 用語集** タブを開いてください。"
            )

    with tab_charts:
        if result:
            _page_charts(result)
        else:
            st.info("バックテスト実行後にチャートが表示されます。")

    with tab_compare:
        _page_compare(st.session_state.compare_rows)

    with tab_cost:
        _page_costs(st.session_state.verify_rows, result)

    with tab_trades:
        _page_trades(result, cfg.get("saved_run"))

    with tab_ml:
        _page_ml(result, cfg.get("saved_run"))

    with tab_strategies:
        render_strategies_tab()

    with tab_glossary:
        render_glossary_tab()


if __name__ == "__main__":
    run_dashboard()
