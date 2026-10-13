"""TSE experiment campaign results (data/reports/experiments/) for Streamlit."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from signalforge.config import data_dir
from signalforge.report.dashboard_explorer import _bar_fig
from signalforge.report.experiment_context import (
    apply_ranking_filters,
    experiment_premises,
    live_strategy_universe,
    paper_forward_summary,
)
from signalforge.experiments.storage import ticker_row_has_core_metrics
from signalforge.report.metrics_ja import (
    EXPECTANCY,
    EXPERIMENT_RANKING_COLUMNS,
    EXPERIMENT_SORT_OPTIONS,
    HELP_PROFIT_FACTOR,
    MAX_DRAWDOWN,
    PROFIT_FACTOR,
    TSE_TABLE_NOTE,
    TRADES,
    WIN_RATE,
    rename_experiment_columns,
)


def _strategies_dir() -> Path:
    return data_dir() / "reports" / "experiments" / "strategies"


def _experiments_dir_mtime() -> float:
    d = _strategies_dir()
    if not d.is_dir():
        return 0.0
    latest = 0.0
    seen: set[Path] = set()
    for pattern in ("*.json", "*.tickers.json", "*.checkpoint.json", "*.checkpoint.tickers.json"):
        for p in d.glob(pattern):
            if p in seen:
                continue
            seen.add(p)
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                continue
    return latest


def experiments_data_updated_label() -> str:
    m = _experiments_dir_mtime()
    if m <= 0:
        return "未生成"
    return datetime.fromtimestamp(m).strftime("%Y-%m-%d %H:%M")


@st.cache_data(ttl=15, show_spinner=False)
def scan_experiment_campaign(_cache_key: float) -> dict[str, Any]:
    from signalforge.experiments.scan import scan_campaign_progress

    return scan_campaign_progress()


def get_experiment_scan() -> dict[str, Any]:
    return scan_experiment_campaign(_experiments_dir_mtime())


def experiment_ranking_strategy_ids() -> list[str]:
    scan = get_experiment_scan()
    return [r["strategy_id"] for r in scan["complete"]]


@st.cache_data(ttl=300, show_spinner=False)
def _cached_ticker_rows(strategy_id: str, sidecar_mtime: float) -> list[dict[str, Any]]:
    from signalforge.experiments.storage import load_strategy_header, load_ticker_rows

    doc = load_strategy_header(strategy_id)
    if not doc:
        return []
    return load_ticker_rows(strategy_id, doc)


def _load_strategy_doc(strategy_id: str) -> dict[str, Any] | None:
    from signalforge.experiments.storage import load_strategy_header

    doc = load_strategy_header(strategy_id)
    if doc and doc.get("complete"):
        return doc
    return None


def _format_ranking_table(df: pd.DataFrame) -> pd.DataFrame:
    out = rename_experiment_columns(df).copy()
    if WIN_RATE in out.columns:
        out[WIN_RATE] = out[WIN_RATE].apply(
            lambda v: f"{float(v):.1%}" if v is not None and v == v else "—"
        )
    for col in (EXPECTANCY, MAX_DRAWDOWN):
        if col in out.columns:
            out[col] = out[col].apply(
                lambda v, c=col: (
                    "—"
                    if v is not None
                    and v == v
                    and c == EXPECTANCY
                    and float(v) <= -20.0
                    else (
                        f"{float(v):+.3f}"
                        if c == EXPECTANCY and v is not None and v == v
                        else (f"{float(v):.1f}" if v is not None and v == v else "—")
                    )
                )
            )
    if PROFIT_FACTOR in out.columns:
        out[PROFIT_FACTOR] = out[PROFIT_FACTOR].apply(
            lambda v: f"{float(v):.2f}" if v is not None and v == v else "—"
        )
    if TRADES in out.columns:
        out[TRADES] = out[TRADES].apply(
            lambda v: f"{int(float(v))}" if v is not None and v == v else "—"
        )
    return out


@st.fragment(run_every=timedelta(seconds=30))
def _render_experiments_live_header(scan: dict[str, Any]) -> None:
    """進捗だけ定期更新（表クリックはフル rerun させるため fragment 外）."""
    n_done = len(scan.get("complete") or [])
    n_plan = int(scan.get("total_planned") or 133)
    st.progress(min(1.0, n_done / n_plan), text=f"完了 {n_done} / {n_plan} 戦略")
    if scan.get("in_progress"):
        with st.expander("実行中", expanded=False):
            for row in scan["in_progress"]:
                tgt = max(1, int(row.get("n_target") or 1))
                done = int(row.get("n_done") or 0)
                st.progress(min(1.0, done / tgt), text=f"{row['strategy_id']} {done}/{tgt}")


def render_experiments_panel() -> None:
    st.subheader("東証 TSE 実験")
    scan = get_experiment_scan()
    n_with_exp = sum(
        1 for r in (scan.get("complete") or []) if r.get("expectancy_pct") is not None
    )
    overall = scan.get("overall") or {}
    ticker_pct = overall.get("ticker_overall_pct")
    extra = f" · 銘柄BT {ticker_pct:.1f}%" if ticker_pct is not None else ""
    st.caption(
        f"{TSE_TABLE_NOTE}  \n"
        f"データ更新 **{experiments_data_updated_label()}** · "
        f"期待値あり **{n_with_exp}** / {len(scan.get('complete') or [])} 戦略{extra} · "
        "30秒ごとに自動更新"
    )

    manifest = scan.get("manifest") or {}

    with st.expander("前提条件", expanded=False):
        for label, text in experiment_premises(manifest).items():
            st.markdown(f"**{label}** — {text}")

    partial = [r for r in scan.get("complete") or [] if r.get("metrics_partial")]
    if partial:
        st.info(
            "指標差し替え中: 表の期待値・最大DD は **再BT済み銘柄だけ** の典型値です。"
            f"（例: {partial[0]['strategy_id']} {partial[0].get('metrics_valid_tickers', 0)}/"
            f"{partial[0].get('metrics_total_tickers', 0)} 銘柄）"
        )

    _render_experiments_live_header(scan)

    if not scan["complete"]:
        st.info("完了した戦略がまだありません。")
        return

    n_missing_exp = sum(
        1
        for r in scan["complete"]
        if r.get("expectancy_pct") is None
        or (r.get("metrics_valid_tickers") or 0) < 5
    )
    if n_missing_exp > len(scan["complete"]) // 2:
        st.warning(
            "期待値・最大DD は **指標再BT** で sidecar に書き込まれます。"
            "いまは損益比・勝率・取引数のみ信頼できます。"
            "再開: `./scripts/rerun-experiments-metrics.sh` または "
            "`uv run signalforge experiments run --ignore-schedule --workers 8 --refresh-metrics`"
        )

    df = pd.DataFrame(scan["complete"])
    if "expectancy_pct" in df.columns:
        df.loc[df["expectancy_pct"].notna() & (df["expectancy_pct"] <= -20.0), "expectancy_pct"] = None
    f1, f2, f3 = st.columns(3)
    with f1:
        min_trades = st.number_input("中央値取引数 ≥", min_value=0, value=0, step=5, key="exp_f_trades")
    with f2:
        pf_gt1 = st.checkbox("損益比 > 1", key="exp_f_pf")
    with f3:
        exp_pos = st.checkbox("期待値 > 0", key="exp_f_exp")

    df = apply_ranking_filters(
        df,
        min_median_trades=float(min_trades),
        profit_factor_gt_1=pf_gt1,
        expectancy_positive=exp_pos,
    )
    if df.empty:
        st.warning("フィルタに一致する戦略がありません。")
        return

    sort_labels = dict(EXPERIMENT_SORT_OPTIONS)
    sort_col = st.selectbox(
        "並び替え",
        options=[k for k, _ in EXPERIMENT_SORT_OPTIONS],
        format_func=lambda k: sort_labels[k],
        key="exp_sort",
    )
    if sort_col not in df.columns:
        sort_col = "profit_factor"
    n_rows = len(df)
    top_n = n_rows if n_rows <= 10 else st.slider("表示件数", 5, min(50, n_rows), min(15, n_rows), key="exp_top")

    show = df.sort_values(sort_col, ascending=False, na_position="last").head(top_n).reset_index(drop=True)
    strategy_ids = show["strategy_id"].astype(str).tolist()
    display = show.copy()
    if "paper_active" in display.columns:
        display["strategy_id"] = display.apply(
            lambda r: f"📈 {r['strategy_id']}" if r.get("paper_active") else r["strategy_id"],
            axis=1,
        )
    if "paper_active" in show.columns and show["paper_active"].any():
        st.caption("📈 = ペーパー稼働中（詳細で BT との比較）")
    cols = [c for c in EXPERIMENT_RANKING_COLUMNS if c in display.columns]
    st.dataframe(
        _format_ranking_table(display[cols]),
        width="stretch",
        hide_index=True,
    )

    from signalforge.report.dashboard_view import render_strategy_detail, sync_strategy_navigation

    cur = st.session_state.get("exp_strategy_row_pick")
    if cur not in strategy_ids:
        st.session_state.pop("exp_strategy_row_pick", None)

    def _pill_label(sid: str) -> str:
        row = show.loc[show["strategy_id"] == sid].iloc[0]
        exp = row.get("expectancy_pct")
        if exp is not None and exp == exp and float(exp) > -20:
            return f"{sid} ({float(exp):+.2f}%)"
        return sid

    st.markdown("**詳細・解説を見る → 戦略名を押す**")
    pick = st.pills(
        "戦略",
        options=strategy_ids,
        format_func=_pill_label,
        selection_mode="single",
        key="exp_strategy_row_pick",
        label_visibility="collapsed",
    )
    if not pick:
        pick = st.selectbox(
            "または一覧から選ぶ",
            options=strategy_ids,
            index=None,
            placeholder="戦略を選択…",
            key="exp_strategy_row_select",
        )
        if pick:
            st.session_state["exp_strategy_row_pick"] = pick
            st.rerun()

    sidebar_pick = st.session_state.get("results_strategy_pick")
    if not pick and sidebar_pick and sidebar_pick != "（一覧のみ）":
        pick = str(sidebar_pick)
    if pick:
        sync_strategy_navigation(str(pick))
        st.divider()
        st.markdown(f"#### `{pick}`")
        render_strategy_detail(str(pick))

    if "expectancy_pct" in df.columns and df["expectancy_pct"].notna().any():
        top = df.sort_values("expectancy_pct", ascending=False, na_position="last").head(min(10, n_rows))
        st.plotly_chart(
            _bar_fig(
                top["strategy_id"].astype(str).tolist(),
                top["expectancy_pct"].astype(float).fillna(0).tolist(),
                f"{EXPECTANCY} Top {len(top)}",
                ytitle=EXPECTANCY,
            ),
            width="stretch",
            key="exp_expectancy_chart",
        )
    elif "profit_factor" in df.columns:
        st.caption("期待値・最大DD は再BT後に表示されます。いまは `experiments aggregate` で損益比等のみ。")

    if st.button("再読み込み", key="exp_rescan"):
        scan_experiment_campaign.clear()
        _cached_ticker_rows.clear()
        st.rerun()


def render_experiment_strategy_detail(strategy_id: str) -> None:
    doc = _load_strategy_doc(strategy_id)
    if not doc:
        st.warning(f"`{strategy_id}` は未完了です。")
        return

    u = live_strategy_universe(strategy_id, doc)
    c1, c2, c3, c4, c5 = st.columns(5)
    exp = u.get("median_avg_pnl_pct")
    if exp is not None and float(exp) <= -20.0:
        exp = None
    c1.metric(EXPECTANCY, f"{float(exp):+.3f}%" if exp is not None else "—")
    c2.metric(PROFIT_FACTOR, f"{float(u.get('median_profit_factor') or 0):.2f}", help=HELP_PROFIT_FACTOR)
    wr = u.get("median_win_rate")
    c3.metric(WIN_RATE, f"{float(wr):.1%}" if wr is not None else "—")
    c4.metric(TRADES, f"{float(u.get('median_trades') or 0):.0f}")
    dd = u.get("median_max_drawdown_pct")
    c5.metric(MAX_DRAWDOWN, f"{float(dd):.1f}%" if dd is not None else "—")

    stored_cap = doc.get("backtest_capital")
    if isinstance(stored_cap, dict) and stored_cap.get("initial_cash_jpy"):
        pct = float(stored_cap.get("max_position_pct") or 1) * 100
        st.caption(
            f"BT 前提: ¥{int(stored_cap['initial_cash_jpy']):,} · 1回上限 {pct:.0f}%"
        )

    paper = paper_forward_summary(strategy_id)
    if paper:
        with st.expander("ペーパー vs TSE BT（代表銘柄）", expanded=False):
            st.markdown(
                f"ペーパー ({paper.get('style_label', paper.get('style'))}) · "
                f"最終更新 {str(paper.get('last_run') or '')[:10] or '—'}"
            )
            bt_pf = u.get("median_profit_factor")
            bt_dd = u.get("median_max_drawdown_pct")
            p_pf = paper.get("profit_factor")
            p_dd = paper.get("max_drawdown_pct")
            cmp_df = pd.DataFrame(
                [
                    {
                        "": "TSE 典型（全銘柄中央値）",
                        PROFIT_FACTOR: f"{float(bt_pf):.2f}" if bt_pf is not None else "—",
                        MAX_DRAWDOWN: f"{float(bt_dd):.1f}%" if bt_dd is not None else "—",
                        "総リターン": "—",
                    },
                    {
                        "": "ペーパー（単一銘柄・フォワード）",
                        PROFIT_FACTOR: f"{float(p_pf):.2f}" if p_pf is not None else "—",
                        MAX_DRAWDOWN: f"{float(p_dd):.1f}%" if p_dd is not None else "—",
                        "総リターン": f"{float(paper.get('total_return_pct') or 0):+.1f}%",
                    },
                ]
            )
            st.dataframe(cmp_df, width="stretch", hide_index=True)
            st.caption("銘柄・期間・口座が異なるため直接比較は参考程度。")

    with st.expander("銘柄別", expanded=False):
        from signalforge.experiments.storage import tickers_sidecar_path

        side = tickers_sidecar_path(strategy_id)
        mtime = side.stat().st_mtime if side.exists() else 0.0
        tickers = _cached_ticker_rows(strategy_id, mtime)
        if tickers:
            tdf = pd.DataFrame(
                [t for t in tickers if not t.get("error") and ticker_row_has_core_metrics(t)]
            )
            if tdf.empty:
                st.caption("再BT済みで有効な銘柄行がまだありません（旧 -65% データは非表示）。")
            if not tdf.empty:
                show_cols = [
                    c
                    for c in [
                        "ticker",
                        "name",
                        "avg_pnl_pct",
                        "profit_factor",
                        "win_rate",
                        "total_trades",
                        "max_drawdown_pct",
                    ]
                    if c in tdf.columns
                ]
                if "avg_pnl_pct" in tdf.columns:
                    tdf = tdf.sort_values("avg_pnl_pct", ascending=False)
                elif "profit_factor" in tdf.columns:
                    tdf = tdf.sort_values("profit_factor", ascending=False)
                st.dataframe(
                    _format_ranking_table(tdf[show_cols].head(30)),
                    width="stretch",
                    hide_index=True,
                )

    from signalforge.report.dashboard_strategies import (
        _render_full_strategy_guide,
        resolve_strategy_guide,
    )

    st.divider()
    st.subheader("📚 戦略解説")
    _render_full_strategy_guide(strategy_id, resolve_strategy_guide(strategy_id))
