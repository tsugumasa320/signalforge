"""Read-only dashboard: browse precomputed strategy / lab / cohort reports."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from signalforge.config import data_dir, load_web_catalog
from signalforge.report.dashboard_experiments import (
    experiment_ranking_strategy_ids,
    experiments_data_updated_label,
    render_experiment_strategy_detail,
    render_experiments_panel,
    get_experiment_scan,
)
from signalforge.report.dashboard_explorer import _load_report, _render_saved_results
from signalforge.report.metrics_ja import HELP_PROFIT_FACTOR, PROFIT_FACTOR


def _reports_dir() -> Path:
    return data_dir() / "reports"


def _file_age(path: Path) -> str:
    if not path.exists():
        return "未生成"
    ts = datetime.fromtimestamp(path.stat().st_mtime)
    return ts.strftime("%Y-%m-%d %H:%M")


def _sidebar_fragment():
    try:
        return st.fragment(run_every=timedelta(seconds=30))
    except TypeError:
        return st.fragment


@_sidebar_fragment()
def _render_tse_sidebar_status() -> None:
    exp_scan = get_experiment_scan()
    n_done = len(exp_scan.get("complete") or [])
    n_plan = int(exp_scan.get("total_planned") or 133)
    overall = exp_scan.get("overall") or {}
    ticker_pct = overall.get("ticker_overall_pct")
    bt_line = f" · 銘柄BT {ticker_pct:.0f}%" if ticker_pct is not None else ""
    active = overall.get("active_strategy_id")
    if active:
        st.sidebar.caption(f"実行中: `{active}`")
    st.sidebar.caption(
        f"TSE 実験: {n_done}/{n_plan} 完了{bt_line} · 更新 {experiments_data_updated_label()}"
    )


def sync_strategy_navigation(strategy_id: str) -> None:
    """戦略解説タブ等と同期（サイドバー selectbox 用は next run で反映）."""
    st.session_state["strategy_guide_pick"] = strategy_id
    st.session_state["exp_focus_strategy"] = strategy_id
    st.session_state["_pending_sidebar_strategy"] = strategy_id


def apply_pending_sidebar_strategy() -> None:
    """サイドバー widgets より前に呼ぶ."""
    pending = st.session_state.pop("_pending_sidebar_strategy", None)
    if pending and pending != "（一覧のみ）":
        st.session_state["results_strategy_pick"] = str(pending)


def dataframe_selected_row_indices(widget_state: Any) -> list[int]:
    """Streamlit 1.59+ DataframeState / legacy dict."""
    if widget_state is None:
        return []
    selection = widget_state.get("selection") if isinstance(widget_state, dict) else getattr(widget_state, "selection", None)
    if selection is None:
        return []
    rows = selection.get("rows") if isinstance(selection, dict) else getattr(selection, "rows", None)
    if not rows:
        return []
    return [int(r) for r in rows]


def apply_experiment_table_navigation() -> None:
    """TSE 一覧の行選択 → 詳細・解説へ（サイドバーより前に呼ぶ）."""
    rows = dataframe_selected_row_indices(st.session_state.get("exp_strategy_pick_table"))
    if not rows:
        return
    ids = st.session_state.get("exp_table_strategy_ids")
    if not isinstance(ids, list) or not ids:
        return
    idx = rows[0]
    if idx < 0 or idx >= len(ids):
        return
    sync_strategy_navigation(str(ids[idx]))


def render_results_sidebar() -> str | None:
    st.sidebar.header("戦略")

    _render_tse_sidebar_status()

    exp_ids = experiment_ranking_strategy_ids()
    catalog = _load_report("catalog_backtests.json")
    ids: list[str] = []
    if exp_ids:
        ids = list(exp_ids)
    elif catalog:
        rows = catalog.get("results") or []
        ok = sorted(
            [r for r in rows if r.get("id") and not r.get("error")],
            key=lambda x: float(x.get("profit_factor") or 0),
            reverse=True,
        )
        ids = [r["id"] for r in ok]
    if not ids:
        cat = load_web_catalog()
        ids = sorted({s["id"] for s in cat.get("strategies", []) if s.get("implemented")})

    return st.sidebar.selectbox(
        "詳細を見る",
        ["（一覧のみ）"] + ids,
        key="results_strategy_pick",
    )


def _strategy_row(strategy_id: str) -> dict[str, Any] | None:
    catalog = _load_report("catalog_backtests.json")
    if not catalog:
        return None
    for r in catalog.get("results") or []:
        if r.get("id") == strategy_id:
            return r
    return None


def _load_strategy_doc_path(strategy_id: str) -> Path:
    return _reports_dir() / "experiments" / "strategies" / f"{strategy_id}.json"


def _strategy_doc_complete(strategy_id: str) -> bool:
    path = _load_strategy_doc_path(strategy_id)
    if not path.exists():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    target = int(doc.get("n_tickers_target") or 0)
    return bool(doc.get("complete")) and target > 0


def render_strategy_detail(strategy_id: str) -> None:
    st.subheader(f"戦略: `{strategy_id}`")
    if _strategy_doc_complete(strategy_id):
        render_experiment_strategy_detail(strategy_id)
        return

    row = _strategy_row(strategy_id)
    if row:
        if row.get("error"):
            st.error(row["error"])
            return
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(PROFIT_FACTOR, f"{float(row.get('profit_factor') or 0):.2f}", help=HELP_PROFIT_FACTOR)
        c2.metric("勝率", f"{float(row.get('win_rate') or 0):.1%}")
        c3.metric("取引数", row.get("total_trades", "—"))
        c4.metric("リターン%", f"{float(row.get('total_return_pct') or 0):+.1f}")
        st.caption(
            f"スタイル: {row.get('style', '?')} · 評価銘柄: {row.get('ticker', '?')} "
            "（カタログ一括 BT の条件）"
        )
    else:
        st.info("カタログ JSON にこの戦略の行がありません。`results build` を実行してください。")

    from signalforge.report.dashboard_strategies import (
        _render_full_strategy_guide,
        resolve_strategy_guide,
    )

    st.divider()
    st.subheader("📚 戦略解説")
    guide = resolve_strategy_guide(strategy_id)
    _render_full_strategy_guide(strategy_id, guide)


def render_results_home() -> None:
    render_experiments_panel()
    with st.expander("カタログ / コホート / ラボ（旧データ）", expanded=False):
        _render_saved_results()
