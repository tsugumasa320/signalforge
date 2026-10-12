"""TSE experiment campaign results (data/reports/experiments/) for Streamlit."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from signalforge.config import data_dir, load_web_catalog
from signalforge.report.dashboard_explorer import _bar_fig, _load_report


def _strategies_dir() -> Path:
    return data_dir() / "reports" / "experiments" / "strategies"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _experiments_dir_mtime() -> float:
    d = _strategies_dir()
    if not d.is_dir():
        return 0.0
    latest = 0.0
    for p in d.glob("*.json"):
        try:
            latest = max(latest, p.stat().st_mtime)
        except OSError:
            continue
    return latest


@st.cache_data(ttl=120, show_spinner=False)
def scan_experiment_campaign(_cache_key: float) -> dict[str, Any]:
    """Scan strategy JSON + checkpoints (no ticker sidecar load)."""
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


@st.fragment
def render_experiments_panel() -> None:
    st.subheader("🇯🇵 東証 TSE 実験（experiments run）")
    st.caption(
        "全内国株式 × 各戦略の **事前バックテスト JSON** を表示。実行中も **完了分だけ** 随時更新されます。"
    )

    scan = get_experiment_scan()
    n_done = len(scan["complete"])
    n_plan = int(scan.get("total_planned") or 133)
    st.progress(min(1.0, n_done / n_plan), text=f"完了戦略 {n_done} / {n_plan}")

    if scan.get("in_progress"):
        with st.expander("実行中・途中保存", expanded=bool(n_done == 0)):
            for row in scan["in_progress"]:
                tgt = max(1, int(row.get("n_target") or 1))
                done = int(row.get("n_done") or 0)
                label = "実行中" if row.get("active") else "checkpoint 保留"
                st.progress(min(1.0, done / tgt), text=f"`{row['strategy_id']}` {done}/{tgt} · {label}")

    if not scan["complete"]:
        st.info(
            "完了した戦略 JSON がまだありません。`uv run signalforge experiments run` 実行後、"
            "ここにランキングが出ます。"
        )
        return

    pool = scan.get("n_tickers_pool") or "—"
    st.caption(f"評価: 銘柄ごと BT → **median PF** を {pool} 銘柄プールで集計（2020-01-01〜キャッシュ最新・`cost_model: japan`）")

    df = pd.DataFrame(scan["complete"])
    sort_col = st.selectbox(
        "並び替え",
        ["median_pf", "mean_pf", "pct_pf_gt_1", "n_tickers"],
        key="exp_sort",
    )
    n_rows = len(df)
    if n_rows <= 5:
        top_n = n_rows
        st.caption(f"表示件数: {top_n}（完了戦略が {n_rows} 件のためスライダー省略）")
    else:
        hi = min(133, n_rows)
        default = min(25, hi)
        top_n = st.slider("表示件数", 5, hi, default, key="exp_top")
    show = df.sort_values(sort_col, ascending=False).head(top_n)
    cols = [c for c in ["strategy_id", "style", "median_pf", "mean_pf", "pct_pf_gt_1", "n_tickers"] if c in show.columns]
    st.dataframe(show[cols], width="stretch", hide_index=True)

    st.plotly_chart(
        _bar_fig(
            show["strategy_id"].astype(str).tolist(),
            show["median_pf"].astype(float).fillna(0).tolist(),
            f"TSE 実験 Top {top_n}（median PF）",
        ),
        width="stretch",
        key="exp_rank_chart",
    )

    seg_doc = _load_report("experiments/matrix_segment.json")
    if seg_doc and (seg_doc.get("cells") or []):
        st.markdown("#### 市場区分 × 戦略（median PF）")
        seg_df = pd.DataFrame(seg_doc["cells"])
        if not seg_df.empty and "median_pf" in seg_df.columns:
            pivot = seg_df.pivot_table(
                index="strategy",
                columns="segment",
                values="median_pf",
                aggfunc="first",
            )
            complete_ids = set(df["strategy_id"])
            pivot = pivot[pivot.index.isin(complete_ids)]
            if not pivot.empty:
                heat = pivot.sort_index()
                st.dataframe(heat, width="stretch")
                with st.expander("ヒートマップ（重い場合は閉じたまま）", expanded=False):
                    try:
                        import plotly.express as px

                        fig = px.imshow(
                            heat.astype(float),
                            labels=dict(x="市場区分", y="戦略", color="median PF"),
                            color_continuous_scale="RdYlGn",
                            aspect="auto",
                            title="市場区分 × 戦略（median PF ヒートマップ）",
                        )
                        fig.update_layout(template="plotly_dark", height=max(280, 28 * len(heat.index)))
                        st.plotly_chart(fig, width="stretch", key="exp_segment_heatmap")
                    except Exception:
                        pass

    if st.button("集計 JSON を再読み込み", key="exp_rescan"):
        scan_experiment_campaign.clear()
        _cached_ticker_rows.clear()
        st.rerun()


def render_experiment_strategy_detail(strategy_id: str) -> None:
    doc = _load_strategy_doc(strategy_id)
    if not doc:
        st.warning(f"`{strategy_id}` は未完了です。完了後に銘柄別の詳細が表示されます。")
        return

    u = doc.get("universe") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Median PF", f"{float(u.get('median_profit_factor') or 0):.2f}")
    c2.metric("Mean PF", f"{float(u.get('mean_profit_factor') or 0):.2f}")
    c3.metric("PF>1 銘柄比率", f"{float(u.get('pct_pf_above_1') or 0):.1%}")
    c4.metric("評価銘柄数", u.get("n_tickers", "—"))

    st.caption(
        f"スタイル: {doc.get('style', '?')} · "
        f"対象 {doc.get('n_tickers_target', '?')} 銘柄 · "
        f"完了 {doc.get('n_tickers_done', '?')}"
    )

    by_seg = doc.get("by_segment") or {}
    if by_seg:
        st.markdown("#### 市場区分")
        seg_rows = [
            {"segment": k, **{kk: vv for kk, vv in (v or {}).items() if kk != "segment"}}
            for k, v in by_seg.items()
        ]
        st.dataframe(pd.DataFrame(seg_rows), width="stretch", hide_index=True)

    by_sec = doc.get("by_sector") or {}
    if by_sec:
        st.markdown("#### 33 業種（median PF 上位 15）")
        sec_rows = [{"sector_tse": k, **(v or {})} for k, v in by_sec.items()]
        sdf = pd.DataFrame(sec_rows)
        if "median_profit_factor" in sdf.columns:
            sdf = sdf.sort_values("median_profit_factor", ascending=False).head(15)
        st.dataframe(sdf, width="stretch", hide_index=True)

    from signalforge.experiments.storage import tickers_sidecar_path

    side = tickers_sidecar_path(strategy_id)
    mtime = side.stat().st_mtime if side.exists() else 0.0
    tickers = _cached_ticker_rows(strategy_id, mtime)
    if not tickers:
        return
    tdf = pd.DataFrame([t for t in tickers if not t.get("error")])
    if tdf.empty:
        return

    st.markdown("#### 銘柄別（抜粋）")
    pf_col = "profit_factor" if "profit_factor" in tdf.columns else None
    if pf_col:
        tdf = tdf.sort_values(pf_col, ascending=False)
    show_cols = [
        c
        for c in [
            "ticker",
            "name",
            "segment",
            "sector_tse",
            "profit_factor",
            "win_rate",
            "total_trades",
            "total_return_pct",
        ]
        if c in tdf.columns
    ]
    tab_top, tab_bot, tab_all = st.tabs(["PF 上位 30", "PF 下位 30", "検索"])
    with tab_top:
        st.dataframe(tdf[show_cols].head(30), width="stretch", hide_index=True)
    with tab_bot:
        st.dataframe(tdf[show_cols].tail(30), width="stretch", hide_index=True)
    with tab_all:
        q = st.text_input("銘柄コード（例: 7203.T）", key=f"exp_ticker_q_{strategy_id}")
        if q.strip():
            hit = tdf[tdf["ticker"].astype(str).str.contains(q.strip(), case=False)]
            st.dataframe(hit[show_cols], width="stretch", hide_index=True)
        else:
            st.caption(f"全 {len(tdf)} 銘柄 — コードを入力して絞り込み")

    from signalforge.report.dashboard_strategies import render_strategy_guide_summary

    with st.expander("📖 戦略解説", expanded=False):
        render_strategy_guide_summary(strategy_id)

    meta = {s["id"]: s for s in load_web_catalog().get("strategies", [])}.get(strategy_id)
    if meta:
        with st.expander("カタログメタデータ"):
            st.write(meta.get("name"), "—", meta.get("summary", ""))
