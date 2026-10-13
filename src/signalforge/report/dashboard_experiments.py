"""TSE experiment campaign results (data/reports/experiments/) for Streamlit."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from signalforge.config import data_dir
from signalforge.report.dashboard_explorer import _bar_fig
from signalforge.report.experiment_context import (
    apply_ranking_filters,
    experiment_premises,
    live_strategy_breakdown,
    live_strategy_universe,
    paper_forward_summary,
)
from signalforge.experiments.storage import ticker_row_has_core_metrics
from signalforge.experiments.period import infer_stored_backtest_period, period_label, periods_match
from signalforge.experiments.scan import (
    TSE_SEGMENT_LABELS,
    apply_cohort_period_slice,
    apply_cohort_to_complete,
    list_campaign_sectors,
)
from signalforge.experiments.series import period_sliceable
from signalforge.report.dashboard_explorer import _default_dates
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
        "30秒ごとに自動更新 · 市場区分・業種・期間（系列データがあれば再BT不要）"
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

    ref_start, ref_end = infer_stored_backtest_period(scan["complete"])
    cfg_start, _ = _default_dates()
    period_presets = [
        "保存済みBTと同じ",
        "直近365日",
        "2020-01-01〜",
        "2023-01-01〜",
        "手動",
    ]
    c_pre, c_ps, c_pe, c_pl = st.columns([1, 1, 1, 1])
    with c_pre:
        period_preset = st.selectbox("期間プリセット", period_presets, key="exp_period_preset")
    preset_start = ref_start or cfg_start
    preset_end = ref_end
    if period_preset == "直近365日":
        preset_start, preset_end = date.today() - timedelta(days=365), None
    elif period_preset == "2020-01-01〜":
        preset_start, preset_end = date(2020, 1, 1), None
    elif period_preset == "2023-01-01〜":
        preset_start, preset_end = date(2023, 1, 1), None
    elif period_preset == "保存済みBTと同じ":
        preset_start, preset_end = ref_start or cfg_start, ref_end
    with c_ps:
        bt_start = st.date_input(
            "開始日",
            value=preset_start,
            disabled=period_preset != "手動",
            key="exp_bt_start",
        )
    with c_pe:
        end_default = preset_end or date.today()
        bt_end_input = st.date_input(
            "終了日",
            value=end_default,
            disabled=period_preset != "手動",
            key="exp_bt_end",
        )
    with c_pl:
        end_is_latest = st.checkbox(
            "終了=最新OHLCV",
            value=preset_end is None,
            disabled=period_preset != "手動",
            key="exp_bt_end_latest",
        )
    if period_preset != "手動":
        bt_start, bt_end = preset_start, preset_end
    else:
        bt_end = None if end_is_latest else bt_end_input

    use_stored_period = periods_match(bt_start, bt_end, ref_start, ref_end)
    period_note = period_label(bt_start, bt_end)
    stored_note = period_label(ref_start, ref_end)

    cohort_labels = ["全体", "プライムのみ", "スタンダードのみ", "グロースのみ", "業種別"]
    c_seg, c_sec = st.columns([1, 1])
    with c_seg:
        cohort_pick = st.selectbox("成績の集計対象", cohort_labels, key="exp_cohort_mode")
    segment: str | None = None
    sector_tse: str | None = None
    cohort_note = "全銘柄（プライム・スタンダード・グロース）"
    if cohort_pick == "プライムのみ":
        segment = "prime"
        cohort_note = TSE_SEGMENT_LABELS["prime"]
    elif cohort_pick == "スタンダードのみ":
        segment = "standard"
        cohort_note = TSE_SEGMENT_LABELS["standard"]
    elif cohort_pick == "グロースのみ":
        segment = "growth"
        cohort_note = TSE_SEGMENT_LABELS["growth"]
    elif cohort_pick == "業種別":
        sectors = list_campaign_sectors()
        with c_sec:
            if not sectors:
                st.caption("業種集計は `experiments aggregate` 後に選べます。")
            else:
                sector_tse = st.selectbox("業種（TSE33）", sectors, key="exp_cohort_sector")
                cohort_note = sector_tse or "—"

    st.session_state["exp_period_start"] = bt_start.isoformat() if bt_start else None
    st.session_state["exp_period_end"] = bt_end.isoformat() if bt_end else None
    st.session_state["exp_period_use_stored"] = use_stored_period
    st.session_state["exp_cohort_segment"] = segment
    st.session_state["exp_cohort_sector"] = sector_tse

    complete_rows: list[dict[str, Any]]
    if use_stored_period:
        complete_rows = apply_cohort_to_complete(
            scan["complete"],
            segment=segment,
            sector_tse=sector_tse,
        )
    else:
        if not period_sliceable(bt_start, bt_end, ref_start, ref_end):
            st.warning(
                f"保存済みBT（{stored_note}）より **前／後** には伸ばせません。"
                "より長い期間が必要ならキャンペーンをその開始日で再実行してください。"
            )
            return
        complete_rows, slice_meta = apply_cohort_period_slice(
            scan["complete"],
            start=bt_start,
            end=bt_end,
            segment=segment,
            sector_tse=sector_tse,
        )
        n_series = int(slice_meta.get("series_tickers") or 0)
        n_total = int(slice_meta.get("total_tickers") or 0)
        if n_total and n_series < n_total:
            st.info(
                f"期間 **{period_note}** をトレード系列から切り出し（系列あり {n_series}/{n_total} 銘柄）。"
                "未追記分: `./scripts/rerun-experiments-series.sh` または "
                "`uv run signalforge experiments run --ignore-schedule --workers 8 --refresh-series`"
            )
        else:
            st.caption(f"期間 **{period_note}** — 保存BT内の切り出し集計（再BTなし）")
        if not complete_rows:
            st.warning(
                "トレード系列（`trades_compact` / `equity_daily`）がまだありません。"
                "上記 `--refresh-series` で1回だけ追記してください。"
            )
            return

    if (segment or sector_tse) and not complete_rows:
        st.warning(f"「{cohort_note}」に該当する sidecar 行がまだありません。")
        return

    df = pd.DataFrame(complete_rows)
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
    rank_cols = list(EXPERIMENT_RANKING_COLUMNS)
    if segment or sector_tse:
        if "n_tickers" not in rank_cols and "n_tickers" in display.columns:
            rank_cols.append("n_tickers")
    cols = [c for c in rank_cols if c in display.columns]
    if segment or sector_tse or not use_stored_period:
        bits = [cohort_note]
        if not use_stored_period:
            bits.append(period_note)
        st.caption(f"表示中: **{' · '.join(bits)}**（該当銘柄のみの典型値）")
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

    ps_raw = st.session_state.get("exp_period_start")
    pe_raw = st.session_state.get("exp_period_end")
    period_start = date.fromisoformat(ps_raw) if ps_raw else None
    period_end = date.fromisoformat(pe_raw) if pe_raw else None
    use_stored = bool(st.session_state.get("exp_period_use_stored", True))
    segment = st.session_state.get("exp_cohort_segment")
    sector_tse = st.session_state.get("exp_cohort_sector")
    ref_start, ref_end = infer_stored_backtest_period([{"strategy_id": strategy_id}])

    u = live_strategy_universe(
        strategy_id,
        doc,
        segment=segment,
        sector_tse=sector_tse,
        period_start=period_start if not use_stored else None,
        period_end=period_end if not use_stored else None,
        stored_period=(ref_start, ref_end),
    )
    if not use_stored:
        st.caption(
            f"詳細指標: 期間 **{period_label(period_start or ref_start, period_end)}**（系列から切り出し）"
        )
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

    by_seg, by_sec = live_strategy_breakdown(strategy_id, doc)
    if by_seg or by_sec:
        with st.expander("市場区分・業種別（典型値）", expanded=False):
            if not use_stored:
                st.caption("期間を変更中のため、内訳は **保存済みBT期間** の sidecar 集計です。")
            if by_seg:
                seg_rows = []
                for seg, s in sorted(by_seg.items(), key=lambda x: x[0]):
                    exp_s = s.get("median_avg_pnl_pct")
                    if exp_s is not None and float(exp_s) <= -20.0:
                        exp_s = None
                    seg_rows.append(
                        {
                            "市場区分": TSE_SEGMENT_LABELS.get(seg, seg),
                            "期待値（%）": exp_s,
                            PROFIT_FACTOR: s.get("median_profit_factor"),
                            WIN_RATE: s.get("median_win_rate"),
                            TRADES: s.get("median_trades"),
                            MAX_DRAWDOWN: s.get("median_max_drawdown_pct"),
                            "評価銘柄数": s.get("n_tickers"),
                        }
                    )
                st.markdown("**市場区分**")
                st.dataframe(
                    _format_ranking_table(pd.DataFrame(seg_rows)),
                    width="stretch",
                    hide_index=True,
                )
            if by_sec:
                sec_rows = []
                for sec, s in sorted(by_sec.items(), key=lambda x: x[0]):
                    exp_s = s.get("median_avg_pnl_pct")
                    if exp_s is not None and float(exp_s) <= -20.0:
                        exp_s = None
                    sec_rows.append(
                        {
                            "業種": sec,
                            "期待値（%）": exp_s,
                            PROFIT_FACTOR: s.get("median_profit_factor"),
                            WIN_RATE: s.get("median_win_rate"),
                            TRADES: s.get("median_trades"),
                            "評価銘柄数": s.get("n_tickers"),
                        }
                    )
                st.markdown("**業種（TSE33）**")
                st.dataframe(
                    _format_ranking_table(pd.DataFrame(sec_rows)),
                    width="stretch",
                    hide_index=True,
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
