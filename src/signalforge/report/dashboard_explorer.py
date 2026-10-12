"""Interactive verification explorer: saved hub results + live backtests with tunable window/tickers."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from signalforge.compare.runner import preset_specs, run_cohort_backtests, resolve_strategy_style
from signalforge.config import data_dir, load_backtest_defaults, load_implementation_map, load_market_config, load_web_catalog
from signalforge.lab.palette import list_palette_rules, resolve_rule_ids
from signalforge.lab.runner import run_rule_study_universe
from signalforge.pipeline import run_backtest_pipeline
from signalforge.universe.filters import get_preset, list_preset_ids, load_equity_meta, resolve_cohort_tickers


def _reports_dir() -> Path:
    return data_dir() / "reports"


def _load_report(name: str) -> dict[str, Any] | None:
    path = _reports_dir() / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _default_dates() -> tuple[date, date | None]:
    bt = load_backtest_defaults()
    start_s = bt.get("backtest_start_date", "2023-01-01")
    start = date.fromisoformat(str(start_s)[:10])
    return start, None


def _cfg_override(
    ticker: str | None,
    start: date | None,
    end: date | None,
) -> dict[str, Any] | None:
    out: dict[str, Any] = {}
    if ticker:
        out["ticker"] = ticker
    if start or end:
        out["backtest"] = {}
        if start:
            out["backtest"]["start_date"] = start.isoformat()
        if end:
            out["backtest"]["end_date"] = end.isoformat()
    return out or None


def _bar_fig(labels: list[str], values: list[float], title: str, ytitle: str = "PF") -> go.Figure:
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=values,
                marker_color=["#22c55e" if v >= 1 else "#ef4444" for v in values],
            )
        ]
    )
    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=420,
        margin=dict(l=40, r=20, t=50, b=120),
        xaxis_tickangle=-45,
        yaxis_title=ytitle,
    )
    return fig


def _catalog_strategy_ids() -> list[str]:
    impl = load_implementation_map().get("strategies") or {}
    if impl:
        return sorted(impl.keys())
    return sorted({s["id"] for s in load_web_catalog().get("strategies", []) if s.get("id")})


def _render_saved_results() -> None:
    st.subheader("📁 事前実行結果（hub / CLI で生成）")
    hub_html = _reports_dir() / "hub" / "index.html"
    if hub_html.exists():
        st.markdown(
            f"静的ハブ（全グラフ）: [`index.html`]({hub_html.resolve().as_uri()})  "
            "— ターミナルから `uv run signalforge hub open` でも開けます。"
        )
    else:
        st.caption("ハブ未生成 → `uv run signalforge hub build` または `hub refresh`")

    source = st.selectbox(
        "データセット",
        ["カタログ単一銘柄 (catalog_backtests.json)", "コホート行列 (compare_matrix.json)", "ラボ行列 (lab_matrix.json)"],
        key="explorer_saved_source",
    )

    if source.startswith("カタログ"):
        doc = _load_report("catalog_backtests.json")
        if not doc:
            st.warning("catalog_backtests.json がありません。`hub build` または `strategies backtest-all` を実行してください。")
            return
        rows = doc.get("results") or []
        df = pd.DataFrame([r for r in rows if not r.get("error")])
        if df.empty:
            st.info("有効な行がありません。")
            return
        sort_col = st.selectbox("並び替え", ["profit_factor", "total_return_pct", "win_rate", "total_trades"], key="cat_sort")
        top_n = st.slider("表示件数", 10, min(133, len(df)), 25, key="cat_top")
        df = df.sort_values(sort_col, ascending=False).head(top_n)
        st.dataframe(
            df[["id", "style", "ticker", "profit_factor", "win_rate", "total_trades", "total_return_pct"]],
            width="stretch",
            hide_index=True,
        )
        st.plotly_chart(
            _bar_fig(
                df["id"].tolist(),
                df["profit_factor"].astype(float).tolist(),
                f"カタログ Top {top_n}（{sort_col}）",
            ),
            width="stretch",
            key="explorer_cat_chart",
        )
        return

    if source.startswith("コホート"):
        doc = _load_report("compare_matrix.json")
        if not doc:
            st.warning("compare_matrix.json がありません。")
            return
        cells = doc.get("cells") or []
        if not cells:
            st.info("セルが空です。")
            return
        cohorts = sorted({c["cohort_id"] for c in cells})
        pick_c = st.multiselect("コホート", cohorts, default=cohorts, key="cmp_cohorts")
        filtered = [c for c in cells if c["cohort_id"] in pick_c]
        rows = []
        for c in filtered:
            s = c.get("summary") or {}
            rows.append(
                {
                    "strategy": c.get("strategy"),
                    "cohort": c.get("cohort_id"),
                    "median_pf": s.get("median_profit_factor"),
                    "mean_pf": s.get("mean_profit_factor"),
                    "n_tickers": s.get("n_tickers"),
                    "pct_pf_gt_1": s.get("pct_pf_above_1"),
                }
            )
        df = pd.DataFrame(rows).dropna(subset=["median_pf"])
        if df.empty:
            st.info("集計可能なデータがありません（古いサンプル行列の可能性）。")
            return
        agg = df.groupby("strategy", as_index=False)["median_pf"].mean().sort_values("median_pf", ascending=False).head(40)
        st.dataframe(df.sort_values("median_pf", ascending=False), width="stretch", hide_index=True)
        st.plotly_chart(
            _bar_fig(agg["strategy"].tolist(), agg["median_pf"].astype(float).tolist(), "戦略別・平均 Median PF"),
            width="stretch",
            key="explorer_cmp_chart",
        )
        return

    doc = _load_report("lab_matrix.json")
    if not doc:
        st.warning("lab_matrix.json がありません。`lab matrix` を実行してください。")
        return
    cells = doc.get("cells") or []
    rows = []
    for c in cells:
        ov = c.get("overview") or c.get("summary") or {}
        rows.append(
            {
                "rule_id": c.get("rule_id"),
                "cohort": c.get("cohort_id"),
                "expectancy_pct": ov.get("expectancy_pct"),
                "profit_factor": ov.get("profit_factor"),
                "win_rate": ov.get("win_rate"),
                "total_trades": ov.get("total_trades"),
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(df.sort_values("expectancy_pct", ascending=False), width="stretch", hide_index=True)
    if not df.empty and df["expectancy_pct"].notna().any():
        pivot = df.pivot_table(index="rule_id", columns="cohort", values="expectancy_pct", aggfunc="mean")
        st.plotly_chart(
            go.Figure(
                data=go.Heatmap(
                    z=pivot.values,
                    x=list(pivot.columns),
                    y=list(pivot.index),
                    colorscale="RdYlGn",
                )
            ).update_layout(title="ラボ · 期待値%ヒートマップ", template="plotly_dark", height=500),
            width="stretch",
            key="explorer_lab_heat",
        )


def _resolve_tickers(mode: str, cohort_id: str, single: str, limit: int) -> list[str]:
    if mode == "単一銘柄":
        return [single.strip()] if single.strip() else []
    if mode == "コホート（プライム等）":
        p = get_preset(cohort_id)
        tickers = resolve_cohort_tickers({**(p.get("filter") or {}), "exclude_etf": True})
    else:
        tickers = sorted(load_equity_meta().get("tickers", {}).keys())
    if limit > 0:
        tickers = tickers[:limit]
    return tickers


def _render_live_runner() -> None:
    st.subheader("▶ 条件を変えて実行")
    st.caption("期間・銘柄・コホートを変えながら、その場でバックテスト／ラボ研究を回せます。")

    mode = st.radio("実行タイプ", ["カタログ戦略（エンジン）", "イザナミラボ（ルール研究）"], horizontal=True, key="live_mode")
    col_a, col_b, col_c = st.columns(3)
    default_start, default_end = _default_dates()
    with col_a:
        start = st.date_input("開始日", value=default_start, key="live_start")
    with col_b:
        end_val = st.date_input("終了日（空=最新）", value=default_end or date.today(), key="live_end")
        end = None if end_val == date.today() and default_end is None else end_val
    with col_c:
        cost = st.selectbox("コスト", ["japan", "legacy", "alpaca"], key="live_cost")

    ticker_mode = st.selectbox("銘柄の選び方", ["単一銘柄", "コホート（プライム等）", "メタ登録全銘柄"], key="live_ticker_mode")
    mc = load_market_config("japan")
    default_t = str(mc.get("default_ticker", "7203.T"))
    c1, c2, c3 = st.columns(3)
    with c1:
        single = st.text_input("銘柄コード", value=default_t, key="live_single", disabled=ticker_mode != "単一銘柄")
    with c2:
        presets = list_preset_ids()
        cohort_id = st.selectbox(
            "コホート",
            [p[0] for p in presets],
            format_func=lambda x: dict(presets).get(x, x),
            key="live_cohort",
            disabled=ticker_mode == "単一銘柄",
        )
    with c3:
        ticker_limit = st.number_input("銘柄上限（0=全部）", min_value=0, max_value=200, value=0, step=5, key="live_limit")

    quick = st.selectbox(
        "期間プリセット",
        ["（手動）", "直近365日", "2020-01-01〜", "2023-01-01〜（デフォルト）"],
        key="live_period_preset",
    )
    if quick == "直近365日":
        start = date.today() - timedelta(days=365)
        end = None
    elif quick == "2020-01-01〜":
        start = date(2020, 1, 1)
        end = None
    elif quick == "2023-01-01〜（デフォルト）":
        start = default_start
        end = default_end

    override = _cfg_override(
        single if ticker_mode == "単一銘柄" else None,
        start,
        end,
    )
    cat_by_id = {s["id"]: s for s in load_web_catalog().get("strategies", [])}

    if mode.startswith("カタログ"):
        ids = _catalog_strategy_ids()
        selected = st.multiselect(
            "戦略（複数可）",
            ids,
            default=[ids[0]] if ids else [],
            key="live_strategies",
        )
        run = st.button("バックテスト実行", type="primary", key="live_run_catalog")
        if run and selected:
            tickers = _resolve_tickers(ticker_mode, cohort_id, single, int(ticker_limit))
            if not tickers:
                st.error("銘柄が選べていません。")
                return
            results: list[dict[str, Any]] = []
            prog = st.progress(0.0)
            total = len(selected) * len(tickers)
            step = 0
            for sid in selected:
                style = resolve_strategy_style(sid, cat_by_id)
                if len(tickers) == 1:
                    try:
                        r = run_backtest_pipeline(
                            style,
                            sid,
                            cost_model=cost,
                            cfg_override={**(override or {}), "ticker": tickers[0]},
                        )
                        m = r.get("metrics") or {}
                        results.append(
                            {
                                "strategy": sid,
                                "ticker": tickers[0],
                                "profit_factor": m.get("profit_factor"),
                                "win_rate": m.get("win_rate"),
                                "total_trades": m.get("total_trades"),
                                "total_return_pct": m.get("total_return_pct"),
                                "window": r.get("backtest_window"),
                            }
                        )
                    except Exception as exc:
                        results.append({"strategy": sid, "ticker": tickers[0], "error": str(exc)})
                    step += 1
                    prog.progress(step / max(total, 1))
                else:
                    block = run_cohort_backtests(
                        strategy_id=sid,
                        style=style,
                        tickers=tickers,
                        cost_model=cost,
                        refresh=False,
                        cfg_override=override,
                    )
                    s = block.get("summary") or {}
                    results.append(
                        {
                            "strategy": sid,
                            "ticker": f"{len(tickers)}銘柄",
                            "profit_factor": s.get("median_profit_factor"),
                            "win_rate": s.get("median_win_rate"),
                            "total_trades": s.get("median_trades"),
                            "total_return_pct": s.get("mean_return_pct"),
                            "window": f"{start}〜{end or '最新'}",
                        }
                    )
                    step += len(tickers)
                    prog.progress(step / max(total, 1))
            prog.empty()
            st.session_state["explorer_live_rows"] = results

        rows = st.session_state.get("explorer_live_rows") or []
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, width="stretch", hide_index=True)
            ok = df[df["profit_factor"].notna()] if "profit_factor" in df.columns else df
            if not ok.empty and "strategy" in ok.columns:
                st.plotly_chart(
                    _bar_fig(
                        ok["strategy"].astype(str).tolist(),
                        ok["profit_factor"].astype(float).tolist(),
                        "実行結果（PF）",
                    ),
                    width="stretch",
                    key="live_cat_result_chart",
                )
        return

    rules = resolve_rule_ids("all")
    rule_labels = {r["id"]: r.get("name", r["id"]) for r in list_palette_rules()}
    rule_id = st.selectbox(
        "ラボルール",
        rules,
        format_func=lambda x: rule_labels.get(x, x),
        key="live_rule",
    )
    run_lab = st.button("ラボ研究を実行", type="primary", key="live_run_lab")
    if run_lab:
        tickers = _resolve_tickers(ticker_mode, cohort_id, single, int(ticker_limit))
        if not tickers:
            st.error("銘柄が選べていません。")
            return
        with st.spinner(f"{rule_id} · {len(tickers)} 銘柄"):
            result = run_rule_study_universe(rule_id, tickers, cfg_override=override)
        st.session_state["explorer_lab_result"] = result

    lab_res = st.session_state.get("explorer_lab_result")
    if lab_res:
        ov = lab_res.get("overview") or lab_res.get("summary") or {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("期待値%", f"{ov.get('expectancy_pct', 0):+.3f}")
        c2.metric("PF", f"{ov.get('profit_factor', 0):.2f}")
        c3.metric("勝率", f"{ov.get('win_rate', 0):.1%}")
        c4.metric("トレード数", ov.get("total_trades", "—"))
        st.json({k: lab_res[k] for k in ("rule_id", "rule_name", "fingerprint") if k in lab_res})
        per = lab_res.get("per_ticker") or []
        if per:
            pdf = pd.DataFrame(per)
            st.dataframe(pdf, width="stretch", hide_index=True)


def render_explorer_tab() -> None:
    st.markdown(
        "事前に `hub build` / `cohort run` / `lab matrix` で溜めた結果の閲覧と、"
        "**期間・銘柄・コホートを変えた再実行**ができます。"
    )
    tab_saved, tab_live = st.tabs(["📁 保存済み結果", "▶ 条件を変えて実行"])
    with tab_saved:
        _render_saved_results()
    with tab_live:
        _render_live_runner()
