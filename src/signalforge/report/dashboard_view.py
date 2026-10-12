"""Read-only dashboard: browse precomputed strategy / lab / cohort reports."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from signalforge.config import data_dir, load_web_catalog
from signalforge.report.dashboard_experiments import (
    experiment_ranking_strategy_ids,
    render_experiment_strategy_detail,
    render_experiments_panel,
    get_experiment_scan,
)
from signalforge.report.dashboard_explorer import _bar_fig, _load_report, _render_saved_results


def _reports_dir() -> Path:
    return data_dir() / "reports"


def _file_age(path: Path) -> str:
    if not path.exists():
        return "未生成"
    ts = datetime.fromtimestamp(path.stat().st_mtime)
    return ts.strftime("%Y-%m-%d %H:%M")


def render_results_sidebar() -> str | None:
    st.sidebar.header("📊 戦略結果")
    st.sidebar.caption("バックテストは **事前実行済み JSON** を表示します。再計算は CLI で行います。")

    paths = {
        "実験(TSE)": _reports_dir() / "experiments" / "manifest.json",
        "カタログ": _reports_dir() / "catalog_backtests.json",
        "コホート": _reports_dir() / "compare_matrix.json",
        "ラボ": _reports_dir() / "lab_matrix.json",
        "ハブ HTML": _reports_dir() / "hub" / "index.html",
    }
    for label, p in paths.items():
        st.sidebar.text(f"{label}: {_file_age(p)}")

    manifest = _load_report("hub/manifest.json")
    if manifest:
        st.sidebar.caption(
            f"最終ビルド: {manifest.get('finished_at', '—')} · "
            f"戦略 {manifest.get('catalog_strategies', '?')} · "
            f"コホート {manifest.get('cohort_cells', '?')} · "
            f"ラボ {manifest.get('lab_cells', '?')}"
        )

    exp_scan = get_experiment_scan()
    if exp_scan.get("complete"):
        st.sidebar.caption(
            f"TSE 実験: 完了 {len(exp_scan['complete'])}/{exp_scan.get('total_planned', 133)} 戦略"
        )

    st.sidebar.markdown(
        "**結果を更新する（ターミナル）**\n"
        "```\n"
        "uv run signalforge experiments aggregate\n"
        "uv run signalforge hub open\n"
        "```"
    )

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
        "戦略を詳しく見る（TSE 実験）",
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


def _cohort_rows(strategy_id: str) -> list[dict[str, Any]]:
    doc = _load_report("compare_matrix.json")
    if not doc:
        return []
    out = []
    for c in doc.get("cells") or []:
        if c.get("strategy") != strategy_id:
            continue
        s = c.get("summary") or {}
        out.append(
            {
                "cohort": c.get("cohort_label") or c.get("cohort_id"),
                "median_pf": s.get("median_profit_factor"),
                "n_tickers": s.get("n_tickers"),
                "pct_pf_gt_1": s.get("pct_pf_above_1"),
            }
        )
    return out


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
        c1.metric("PF", f"{float(row.get('profit_factor') or 0):.2f}")
        c2.metric("勝率", f"{float(row.get('win_rate') or 0):.1%}")
        c3.metric("取引数", row.get("total_trades", "—"))
        c4.metric("リターン%", f"{float(row.get('total_return_pct') or 0):+.1f}")
        st.caption(
            f"スタイル: {row.get('style', '?')} · 評価銘柄: {row.get('ticker', '?')} "
            "（カタログ一括 BT の条件）"
        )
    else:
        st.info("カタログ JSON にこの戦略の行がありません。`results build` を実行してください。")

    cohort = _cohort_rows(strategy_id)
    if cohort:
        st.markdown("#### コホート別（事前計算）")
        cdf = pd.DataFrame(cohort)
        st.dataframe(cdf, width="stretch", hide_index=True)
        if cdf["median_pf"].notna().any():
            st.plotly_chart(
                _bar_fig(
                    cdf["cohort"].astype(str).tolist(),
                    cdf["median_pf"].astype(float).fillna(0).tolist(),
                    "Median PF by cohort",
                ),
                width="stretch",
                key=f"detail_cohort_{strategy_id}",
            )

    from signalforge.report.dashboard_strategies import render_strategy_guide_summary

    with st.expander("📖 戦略解説（エントリー・決済）", expanded=False):
        render_strategy_guide_summary(strategy_id)

    meta = {s["id"]: s for s in load_web_catalog().get("strategies", [])}.get(strategy_id)
    if meta:
        with st.expander("カタログメタデータ"):
            st.write(meta.get("name"), "—", meta.get("summary", ""))
            st.caption(f"タグ: {', '.join(meta.get('tags') or [])}")


def render_results_home() -> None:
    st.markdown(
        "全戦略・コホート・ラボルールは **あらかじめバックテスト済み** です。"
        "ここでは保存された結果を **閲覧・比較** するだけで OK です。"
    )
    render_experiments_panel()
    st.divider()
    with st.expander("従来のカタログ / コホート / ラボ", expanded=False):
        _render_saved_results()
