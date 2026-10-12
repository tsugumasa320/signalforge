"""Streamlit tab: Izanami-style lab rule studies with tunable window and universe."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from signalforge.config import load_backtest_defaults, load_market_config
from signalforge.lab.palette import list_palette_rules, resolve_rule_ids
from signalforge.lab.runner import run_rule_study_universe
from signalforge.report.dashboard_explorer import _cfg_override, _load_report, _resolve_tickers
from signalforge.universe.filters import list_preset_ids


def render_lab_tab() -> None:
    st.subheader("🔬 イザナミラボ（ルール研究）")
    st.caption(
        "資金制約なしのルール検証 → 結果概要 → 分散投資近似。"
        " CLI: `uv run signalforge lab backtest --rule iz_macd_buy --cohort prime`"
    )

    matrix = _load_report("lab_matrix.json")
    if matrix and matrix.get("cells"):
        with st.expander("事前計算 lab_matrix（クリックで一覧）", expanded=False):
            rows = []
            for c in matrix["cells"]:
                ov = c.get("overview") or c.get("summary") or {}
                rows.append(
                    {
                        "rule": c.get("rule_id"),
                        "cohort": c.get("cohort_id"),
                        "expectancy_pct": ov.get("expectancy_pct"),
                        "pf": ov.get("profit_factor"),
                    }
                )
            st.dataframe(pd.DataFrame(rows).sort_values("expectancy_pct", ascending=False), hide_index=True)

    rules = list_palette_rules()
    rule_ids = resolve_rule_ids("all")
    labels = {r["id"]: r.get("name", r["id"]) for r in rules}

    col1, col2 = st.columns(2)
    with col1:
        rule_id = st.selectbox("ルール", rule_ids, format_func=lambda x: labels.get(x, x), key="lab_tab_rule")
    with col2:
        presets = list_preset_ids()
        cohort_id = st.selectbox(
            "コホート",
            [p[0] for p in presets],
            format_func=lambda x: dict(presets).get(x, x),
            key="lab_tab_cohort",
        )

    bt = load_backtest_defaults()
    default_start = date.fromisoformat(str(bt.get("backtest_start_date", "2023-01-01"))[:10])
    mc = load_market_config("japan")
    c3, c4, c5 = st.columns(3)
    with c3:
        start = st.date_input("開始日", value=default_start, key="lab_tab_start")
    with c4:
        lab_use_end = st.checkbox("終了日指定", value=False, key="lab_tab_use_end")
        end = st.date_input("終了日", value=date.today(), disabled=not lab_use_end, key="lab_tab_end")
    with c5:
        limit = st.number_input("銘柄上限", 0, 100, 0, key="lab_tab_limit")

    use_cache = st.checkbox("キャッシュ利用（増分銘柄）", value=True, key="lab_tab_cache")
    if st.button("この条件でラボ実行", type="primary", key="lab_tab_run"):
        tickers = _resolve_tickers("コホート（プライム等）", cohort_id, "", int(limit))
        override = _cfg_override(None, start, end if lab_use_end else None)
        with st.spinner(f"{len(tickers)} 銘柄 · {rule_id}"):
            result = run_rule_study_universe(
                rule_id,
                tickers,
                cfg_override=override,
                use_cache=use_cache,
                save_cache=True,
            )
        st.session_state["lab_tab_result"] = result

    res = st.session_state.get("lab_tab_result")
    if not res:
        st.info("ルールとコホートを選び **この条件でラボ実行** を押してください。")
        return

    ov = res.get("overview") or res.get("summary") or {}
    st.markdown(f"**{res.get('rule_name', rule_id)}** · fingerprint `{res.get('fingerprint', '—')}`")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("期待値 %", f"{ov.get('expectancy_pct', 0):+.3f}")
    m2.metric("PF", f"{ov.get('profit_factor', 0):.2f}")
    m3.metric("Fill率", f"{ov.get('fill_rate', 0):.1%}")
    m4.metric("Signals", ov.get("total_entry_signals", "—"))

    ps = res.get("portfolio_sim") or {}
    if ps:
        st.markdown(
            f"**分散近似** Final ¥{ps.get('final_equity', 0):,.0f} · "
            f"Return {ps.get('total_return_pct', 0):+.2f}% · "
            f"accepted {ps.get('accepted_trades')} / skip overlap {ps.get('skipped_overlap')}"
        )
