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
from signalforge.experiments.cohort_matrix import build_cohort_matrix
from signalforge.experiments.scan import (
    apply_cohort_period_slice,
    apply_cohort_to_complete,
    list_campaign_sectors,
)
from signalforge.experiments.ticker_cohort import TSE_SEGMENT_LABELS
from signalforge.experiments.series import period_sliceable
from signalforge.report.dashboard_explorer import _default_dates
from signalforge.report.metrics_ja import (
    EXPECTANCY,
    EXPERIMENT_DF_COLUMNS,
    EXPERIMENT_RANKING_COLUMNS,
    EXPERIMENT_SORT_OPTIONS,
    HELP_PROFIT_FACTOR,
    MAX_DRAWDOWN,
    PROFIT_FACTOR,
    STRATEGY_CATEGORY,
    STRATEGY_RANK,
    STRATEGY_SUMMARY,
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


@st.cache_data(ttl=30, show_spinner="TSE 実験データを読み込み中…")
def scan_experiment_campaign(_cache_key: float) -> dict[str, Any]:
    from signalforge.experiments.scan import scan_campaign_progress

    # fast=True: ヘッダ JSON のみ（sidecar 全読込は数分かかるためダッシュボード用）
    return scan_campaign_progress(fast=True)


def get_experiment_scan() -> dict[str, Any]:
    return scan_experiment_campaign(_experiments_dir_mtime())


@st.cache_data(ttl=30, show_spinner=False)
def _segment_cohort_rows_cached(
    _cache_key: float,
    segment: str,
    sector_tse: str | None,
) -> list[dict[str, Any]]:
    """by_segment / by_sector ヘッダのみ（sidecar 全読込を避ける）."""
    scan = scan_experiment_campaign(_cache_key)
    return apply_cohort_to_complete(
        scan["complete"],
        segment=segment,
        sector_tse=sector_tse,
        header_only=True,
    )


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


def _attach_strategy_catalog_fields(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "strategy_id" not in df.columns:
        return df
    from signalforge.report.strategy_guide_builder import (
        resolve_strategy_guide,
        strategy_category_label,
        strategy_style_label,
    )

    out = df.copy()
    sids = out["strategy_id"].astype(str)
    out["strategy_summary"] = sids.map(
        lambda sid: (resolve_strategy_guide(sid).get("summary") or "—").strip()
    )
    out["strategy_category"] = sids.map(strategy_category_label)
    out["style"] = sids.map(strategy_style_label)
    return out


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
    from signalforge.report.metrics_ja import PORTFOLIO_RETURN

    if PORTFOLIO_RETURN in out.columns:
        out[PORTFOLIO_RETURN] = out[PORTFOLIO_RETURN].apply(
            lambda v: f"{float(v):+.2f}" if v is not None and v == v else "—"
        )
    if TRADES in out.columns:
        out[TRADES] = out[TRADES].apply(
            lambda v: f"{int(float(v))}" if v is not None and v == v else "—"
        )
    from signalforge.report.metrics_ja import METRICS_NOTE

    if METRICS_NOTE in out.columns:
        out[METRICS_NOTE] = out[METRICS_NOTE].apply(
            lambda v: str(v).strip() if v is not None and v == v and str(v).strip() else "—"
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


def _experiment_cohort_rows(
    scan_complete: list[dict[str, Any]],
    *,
    use_stored_period: bool,
    bt_start: date | None,
    bt_end: date | None,
    ref_start: date | None,
    ref_end: date | None,
    segment: str | None,
    sector_tse: str | None,
    header_only: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if use_stored_period:
        return (
            apply_cohort_to_complete(
                scan_complete,
                segment=segment,
                sector_tse=sector_tse,
                header_only=header_only,
            ),
            None,
        )
    if bt_start is None or ref_start is None:
        return [], None
    if not period_sliceable(bt_start, bt_end, ref_start, ref_end):
        return [], None
    rows, meta = apply_cohort_period_slice(
        scan_complete,
        start=bt_start,
        end=bt_end,
        segment=segment,
        sector_tse=sector_tse,
    )
    return rows, meta


def _prepare_ranking_dataframe(
    rows: list[dict[str, Any]],
    *,
    min_median_trades: float,
    profit_factor_gt_1: bool,
    expectancy_positive: bool,
) -> pd.DataFrame:
    from signalforge.alt_data.trust import apply_trust_to_row

    if rows:
        rows = [apply_trust_to_row(dict(r)) for r in rows]
        from signalforge.experiments.portfolio_returns import load_portfolio_returns_cache

        cache = load_portfolio_returns_cache()
        by_sid = (cache.get("strategies") or {}) if isinstance(cache, dict) else {}
        if by_sid:
            for r in rows:
                sid = str(r.get("strategy_id") or "")
                hit = by_sid.get(sid) or {}
                tr = hit.get("total_return_pct")
                if tr is not None and not isinstance(hit.get("error"), str):
                    r["portfolio_return_pct"] = tr
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if "expectancy_pct" in df.columns:
        df.loc[
            df["expectancy_pct"].notna() & (df["expectancy_pct"] <= -20.0),
            "expectancy_pct",
        ] = None
    return apply_ranking_filters(
        df,
        min_median_trades=min_median_trades,
        profit_factor_gt_1=profit_factor_gt_1,
        expectancy_positive=expectancy_positive,
    )


def _render_expectancy_bar_chart(
    chart_df: pd.DataFrame,
    *,
    title: str,
    chart_key: str,
) -> None:
    top = (
        chart_df.sort_values("expectancy_pct", ascending=False, na_position="last")
        .dropna(subset=["expectancy_pct"])
    )
    if top.empty:
        return
    labels = [
        f"{i + 1}. {sid}"
        for i, sid in enumerate(top["strategy_id"].astype(str).tolist())
    ]
    st.plotly_chart(
        _bar_fig(
            labels,
            top["expectancy_pct"].astype(float).tolist(),
            title,
            ytitle=EXPECTANCY,
        ),
        width="stretch",
        key=chart_key,
    )


@st.cache_data(ttl=60, show_spinner=False)
def _cached_cohort_matrix(
    _mtime: float,
    complete_flags: tuple[tuple[str, bool | None, str | None], ...],
) -> pd.DataFrame:
    complete = [
        {"strategy_id": sid, "metrics_trusted": trusted, "metrics_note": note}
        for sid, trusted, note in complete_flags
    ]
    rows = build_cohort_matrix(complete)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _render_cohort_breakdown_table(complete: list[dict[str, Any]]) -> None:
    st.markdown("#### 区分・業種別 成績一覧")
    st.caption(
        "戦略 × **全体 / 市場区分 / 33業種** の組み合わせ（`experiments aggregate` の典型値）。"
        "上の期間フィルタは **メイン表のみ**；ここは保存BTの **全期間** 集計です。"
    )
    flags = tuple(
        (
            str(r.get("strategy_id")),
            r.get("metrics_trusted"),
            r.get("metrics_note"),
        )
        for r in complete
        if r.get("strategy_id")
    )
    if not flags:
        st.info("完了戦略がありません。")
        return
    raw = _cached_cohort_matrix(_experiments_dir_mtime(), flags)
    if raw.empty:
        st.info("区分・業種集計がありません。`uv run signalforge experiments aggregate` を実行してください。")
        return

    df = _attach_strategy_catalog_fields(raw)
    kind_labels = {"universe": "全体", "segment": "市場区分", "sector": "業種（TSE33）"}
    df["cohort_kind_ja"] = df["cohort_kind"].map(kind_labels).fillna(df["cohort_kind"])

    f1, f2, f3 = st.columns([1, 1, 1])
    with f1:
        kinds = st.multiselect(
            "集計種別",
            options=sorted(df["cohort_kind_ja"].unique()),
            default=sorted(df["cohort_kind_ja"].unique()),
            key="cohort_matrix_kinds",
        )
    with f2:
        strategies = st.multiselect(
            "戦略（空=全件）",
            options=sorted(df["strategy_id"].unique()),
            default=[],
            key="cohort_matrix_strategies",
        )
    with f3:
        min_n = st.number_input("評価銘柄数 ≥", min_value=0, value=10, step=5, key="cohort_matrix_min_n")

    view = df[df["cohort_kind_ja"].isin(kinds)] if kinds else df
    if strategies:
        view = view[view["strategy_id"].isin(strategies)]
    if min_n > 0 and "n_tickers" in view.columns:
        view = view[view["n_tickers"].fillna(0) >= min_n]

    tab_long, tab_wide = st.tabs(["一覧（長形式）", "市場区分ヒートマップ（期待値）"])
    display_cols = [
        "strategy_id",
        "strategy_category",
        "cohort_kind_ja",
        "cohort_label",
        "expectancy_pct",
        "profit_factor",
        "median_return_pct",
        "win_rate",
        "total_trades",
        "max_drawdown_pct",
        "n_tickers",
        "metrics_note",
    ]
    with tab_long:
        sort = st.selectbox(
            "並び替え",
            ["expectancy_pct", "profit_factor", "median_return_pct", "strategy_id", "cohort_label"],
            format_func=lambda k: rename_experiment_columns(pd.DataFrame(columns=[k])).columns[0]
            if k in EXPERIMENT_DF_COLUMNS
            else k,
            key="cohort_matrix_sort",
        )
        show = view.sort_values(sort, ascending=False, na_position="last")
        st.caption(f"{len(show)} 行")
        st.dataframe(_format_ranking_table(show[[c for c in display_cols if c in show.columns]]), width="stretch")
        csv = show.to_csv(index=False).encode("utf-8-sig")
        st.download_button("CSV ダウンロード", csv, "tse_cohort_matrix.csv", "text/csv", key="cohort_matrix_csv")

    with tab_wide:
        seg = view[view["cohort_kind"] == "segment"].copy()
        if seg.empty or seg["expectancy_pct"].notna().sum() == 0:
            st.caption("市場区分の期待値データがありません。")
        else:
            top_n = st.slider("戦略数（全体期待値上位）", 5, 40, 20, key="cohort_heat_n")
            uni = view[view["cohort_kind"] == "universe"].sort_values("expectancy_pct", ascending=False)
            pick = uni.head(top_n)["strategy_id"].tolist()
            seg = seg[seg["strategy_id"].isin(pick)]
            pivot = seg.pivot_table(
                index="strategy_id",
                columns="cohort_label",
                values="expectancy_pct",
                aggfunc="first",
            )
            col_order = [TSE_SEGMENT_LABELS[k] for k in ("prime", "standard", "growth") if TSE_SEGMENT_LABELS[k] in pivot.columns]
            pivot = pivot[[c for c in col_order if c in pivot.columns]]
            st.dataframe(
                pivot.map(lambda v: f"{v:+.3f}" if v == v else "—"),
                width="stretch",
            )


def _render_segment_expectancy_charts(
    scan_complete: list[dict[str, Any]],
    *,
    use_stored_period: bool,
    bt_start: date | None,
    bt_end: date | None,
    ref_start: date | None,
    ref_end: date | None,
    sector_tse: str | None,
    period_note: str,
    min_median_trades: float,
    profit_factor_gt_1: bool,
    expectancy_positive: bool,
) -> None:
    st.markdown("#### 市場区分別（期待値）")
    caption_bits: list[str] = ["表と同じフィルタを適用"]
    if sector_tse:
        caption_bits.append(f"業種: {sector_tse}")
    if not use_stored_period:
        caption_bits.append(f"期間: {period_note}")
    st.caption(" · ".join(caption_bits))
    cache_key = _experiments_dir_mtime()
    for seg_key, label in TSE_SEGMENT_LABELS.items():
        if use_stored_period:
            rows = _segment_cohort_rows_cached(cache_key, seg_key, sector_tse)
        else:
            rows, _ = _experiment_cohort_rows(
                scan_complete,
                use_stored_period=use_stored_period,
                bt_start=bt_start,
                bt_end=bt_end,
                ref_start=ref_start,
                ref_end=ref_end,
                segment=seg_key,
                sector_tse=sector_tse,
                header_only=False,
            )
        seg_df = _prepare_ranking_dataframe(
            rows,
            min_median_trades=min_median_trades,
            profit_factor_gt_1=profit_factor_gt_1,
            expectancy_positive=expectancy_positive,
        )
        if seg_df.empty or "expectancy_pct" not in seg_df.columns:
            st.caption(f"{label}: フィルタに一致する戦略がありません")
            continue
        n_show = int(seg_df["expectancy_pct"].notna().sum())
        if n_show == 0:
            st.caption(f"{label}: 期待値データなし")
            continue
        _render_expectancy_bar_chart(
            seg_df,
            title=f"{label} · {EXPECTANCY}（{n_show} 戦略）",
            chart_key=f"exp_seg_chart_{seg_key}",
        )


def render_experiments_panel() -> None:
    st.subheader("東証 TSE 実験")
    scan = get_experiment_scan()
    n_with_exp = sum(
        1
        for r in (scan.get("complete") or [])
        if r.get("metrics_trusted") and r.get("expectancy_pct") is not None
    )
    n_untrusted = sum(
        1 for r in (scan.get("complete") or []) if r.get("metrics_trusted") is False
    )
    overall = scan.get("overall") or {}
    ticker_pct = overall.get("ticker_overall_pct")
    extra = f" · 銘柄BT {ticker_pct:.1f}%" if ticker_pct is not None else ""
    st.caption(
        f"{TSE_TABLE_NOTE}  \n"
        f"データ更新 **{experiments_data_updated_label()}** · "
        f"信頼できる期待値 **{n_with_exp}** / {len(scan.get('complete') or [])} 戦略{extra} · "
        "30秒ごとに自動更新 · 市場区分・業種・期間（系列データがあれば再BT不要）"
    )
    if n_untrusted:
        st.caption(
            f"**データ列:** 代理BT・未取得データの戦略 **{n_untrusted}** 件は数値を **—** で表示（誤解防止）。"
            "本データ戦略は `alt-data` 取得後に再BT。"
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

    if not use_stored_period and not period_sliceable(bt_start, bt_end, ref_start, ref_end):
        st.warning(
            f"保存済みBT（{stored_note}）より **前／後** には伸ばせません。"
            "より長い期間が必要ならキャンペーンをその開始日で再実行してください。"
        )
        return
    complete_rows, slice_meta = _experiment_cohort_rows(
        scan["complete"],
        use_stored_period=use_stored_period,
        bt_start=bt_start,
        bt_end=bt_end,
        ref_start=ref_start,
        ref_end=ref_end,
        segment=segment,
        sector_tse=sector_tse,
    )
    if not use_stored_period:
        slice_meta = slice_meta or {}
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

    f1, f2, f3 = st.columns(3)
    with f1:
        min_trades = st.number_input("中央値取引数 ≥", min_value=0, value=0, step=5, key="exp_f_trades")
    with f2:
        pf_gt1 = st.checkbox("損益比 > 1", key="exp_f_pf")
    with f3:
        exp_pos = st.checkbox("期待値 > 0", key="exp_f_exp")

    df = _prepare_ranking_dataframe(
        complete_rows,
        min_median_trades=float(min_trades),
        profit_factor_gt_1=pf_gt1,
        expectancy_positive=exp_pos,
    )

    show_expectancy_charts = n_with_exp > 0
    if show_expectancy_charts:
        if not df.empty and "expectancy_pct" in df.columns and df["expectancy_pct"].notna().any():
            n_chart = int(df["expectancy_pct"].notna().sum())
            bits = [cohort_note, f"{n_chart} 戦略"]
            if not use_stored_period:
                bits.append(period_note)
            _render_expectancy_bar_chart(
                df,
                title=f"{EXPECTANCY} · {' · '.join(bits)}",
                chart_key="exp_expectancy_chart",
            )
        elif not df.empty:
            st.caption("フィルタ後の戦略に期待値がありません。")
        _render_segment_expectancy_charts(
            scan["complete"],
            use_stored_period=use_stored_period,
            bt_start=bt_start,
            bt_end=bt_end,
            ref_start=ref_start,
            ref_end=ref_end,
            sector_tse=sector_tse,
            period_note=period_note,
            min_median_trades=float(min_trades),
            profit_factor_gt_1=pf_gt1,
            expectancy_positive=exp_pos,
        )
        st.divider()

    if df.empty:
        st.warning("フィルタに一致する戦略がありません。")
    else:
        _render_experiment_ranking_table(
            df,
            segment=segment,
            sector_tse=sector_tse,
            use_stored_period=use_stored_period,
            cohort_note=cohort_note,
            period_note=period_note,
        )

    if not show_expectancy_charts and not df.empty and "profit_factor" in df.columns:
        st.caption("期待値・最大DD は再BT後に表示されます。いまは `experiments aggregate` で損益比等のみ。")

    st.divider()
    _render_cohort_breakdown_table(scan.get("complete") or [])

    if st.button("再読み込み", key="exp_rescan"):
        scan_experiment_campaign.clear()
        _segment_cohort_rows_cached.clear()
        _cached_cohort_matrix.clear()
        _cached_ticker_rows.clear()
        st.rerun()


def _render_experiment_ranking_table(
    df: pd.DataFrame,
    *,
    segment: str | None,
    sector_tse: str | None,
    use_stored_period: bool,
    cohort_note: str,
    period_note: str,
) -> None:
    from signalforge.report.dashboard_view import render_strategy_detail, sync_strategy_navigation

    sort_labels = dict(EXPERIMENT_SORT_OPTIONS)
    sort_col = st.selectbox(
        "並び替え",
        options=[k for k, _ in EXPERIMENT_SORT_OPTIONS],
        format_func=lambda k: sort_labels[k],
        key="exp_sort",
    )
    if sort_col not in df.columns:
        sort_col = "profit_factor"
    show = (
        df.sort_values(sort_col, ascending=False, na_position="last")
        .reset_index(drop=True)
    )
    show.insert(0, "rank", range(1, len(show) + 1))
    strategy_ids = show["strategy_id"].astype(str).tolist()
    display = _attach_strategy_catalog_fields(show)
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
    st.caption(f"**#** は現在の並び替え（{sort_labels.get(sort_col, sort_col)}）での順位です。")
    if "portfolio_return_pct" not in show.columns or show["portfolio_return_pct"].isna().all():
        st.caption(
            "1口座リターン列は `uv run signalforge experiments portfolio-all` で "
            "`data/reports/experiments/portfolio_returns.json` を生成すると表示されます。"
        )
    table_out = _format_ranking_table(display[cols])
    col_cfg = {}
    if STRATEGY_RANK in table_out.columns:
        col_cfg[STRATEGY_RANK] = st.column_config.NumberColumn(
            STRATEGY_RANK,
            width="small",
            format="%d",
        )
    if STRATEGY_CATEGORY in table_out.columns:
        col_cfg[STRATEGY_CATEGORY] = st.column_config.TextColumn(
            STRATEGY_CATEGORY,
            width="medium",
            help="web_catalog.yaml の tags（日本語ラベル）",
        )
    if STRATEGY_SUMMARY in table_out.columns:
        col_cfg[STRATEGY_SUMMARY] = st.column_config.TextColumn(
            STRATEGY_SUMMARY,
            width="large",
            help="📚 戦略解説タブと同じ概要文",
        )
    st.dataframe(
        table_out,
        width="stretch",
        hide_index=True,
        **({"column_config": col_cfg} if col_cfg else {}),
    )

    cur = st.session_state.get("exp_strategy_row_pick")
    if cur not in strategy_ids:
        st.session_state.pop("exp_strategy_row_pick", None)

    def _pill_label(sid: str) -> str:
        row = show.loc[show["strategy_id"] == sid].iloc[0]
        n = int(row["rank"])
        exp = row.get("expectancy_pct")
        if exp is not None and exp == exp and float(exp) > -20:
            return f"#{n} {sid} ({float(exp):+.2f}%)"
        return f"#{n} {sid}"

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
