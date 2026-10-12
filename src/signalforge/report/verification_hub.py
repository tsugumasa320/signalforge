"""Unified ranking + charts from catalog / cohort / lab JSON reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import plotly.graph_objects as go

from signalforge.config import data_dir
from signalforge.report.static_html import BASE_CSS, fig_to_html_block, wrap_page


def _reports_dir() -> Path:
    return data_dir() / "reports"


def _hub_dir() -> Path:
    p = _reports_dir() / "hub"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_json(name: str) -> dict[str, Any] | None:
    path = _reports_dir() / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _rank_table(rows: list[dict], sort_key: str, limit: int = 50) -> str:
    valid = [r for r in rows if r.get(sort_key) is not None and r.get("error") is None]
    valid.sort(key=lambda x: float(x.get(sort_key) or 0), reverse=True)
    lines = [
        "<table><thead><tr><th>#</th><th>ID</th><th>PF</th><th>Win%</th>"
        "<th>Trades</th><th>Return%</th></tr></thead><tbody>"
    ]
    for i, r in enumerate(valid[:limit], 1):
        pf = float(r.get("profit_factor") or 0)
        wr = float(r.get("win_rate") or 0) * 100
        tr = r.get("total_trades", "—")
        ret = r.get("total_return_pct")
        ret_s = f"{float(ret):+.1f}" if ret is not None else "—"
        cls = "positive" if pf >= 1 else "negative"
        lines.append(
            f"<tr><td>{i}</td><td><code>{r.get('id','?')}</code></td>"
            f'<td class="{cls}">{pf:.2f}</td><td>{wr:.1f}</td><td>{tr}</td><td>{ret_s}</td></tr>'
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


def _bar_chart(ids: list[str], values: list[float], title: str, ytitle: str) -> go.Figure:
    fig = go.Figure(
        data=[go.Bar(x=ids, y=values, marker_color=["#22c55e" if v >= 1 else "#ef4444" for v in values])]
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


def _heatmap(
    strategies: list[str],
    cohorts: list[str],
    matrix: list[list[float | None]],
    title: str,
) -> go.Figure:
    z = [[v if v is not None else 0 for v in row] for row in matrix]
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=cohorts,
            y=strategies,
            colorscale="RdYlGn",
            zmid=1.0,
        )
    )
    fig.update_layout(title=title, template="plotly_dark", height=max(400, len(strategies) * 14))
    return fig


def build_verification_hub() -> Path:
    catalog = _load_json("catalog_backtests.json")
    compare = _load_json("compare_matrix.json")
    lab = _load_json("lab_matrix.json")
    manifest = _load_json("hub/manifest.json") or {}

    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    sections: list[str] = []

    sections.append(
        f'<div class="info-box">最終ビルド: {manifest.get("finished_at", "—")} · '
        f"カタログ {manifest.get('catalog_strategies', '?')} 戦略 · "
        f"コホート {manifest.get('cohort_cells', '?')} セル · "
        f"ラボ {manifest.get('lab_cells', '?')} セル</div>"
    )

    if catalog:
        rows = catalog.get("results") or []
        top = sorted(
            [r for r in rows if r.get("profit_factor") is not None and not r.get("error")],
            key=lambda x: float(x["profit_factor"]),
            reverse=True,
        )[:25]
        ids = [r["id"] for r in top]
        pfs = [float(r["profit_factor"]) for r in top]
        n_t = (catalog.get("meta") or {}).get("n_tickers", "?")
        fig = _bar_chart(ids, pfs, f"カタログ戦略ランキング（Top 25 · 東証{n_t}銘柄 median PF）", "Profit Factor")
        sections.append("<section id='catalog'><h2>📊 カタログ全戦略（東証ユニバース）</h2>")
        sections.append(fig_to_html_block(fig, include_plotlyjs="cdn", div_id="chart_catalog"))
        sections.append("<h3>ランキング表</h3>")
        sections.append(_rank_table(rows, "profit_factor", limit=133))
        sections.append("</section>")

    if compare:
        cells = compare.get("cells") or []
        cohort_ids = sorted({c["cohort_id"] for c in cells})
        strat_ids = sorted({c["strategy"] for c in cells})
        pivot: dict[str, dict[str, float | None]] = {}
        for c in cells:
            pf = (c.get("summary") or {}).get("median_profit_factor")
            pivot.setdefault(c["strategy"], {})[c["cohort_id"]] = pf
        # Top 40 strategies by avg PF across cohorts
        scored = []
        for sid in strat_ids:
            vals = [pivot.get(sid, {}).get(cid) for cid in cohort_ids]
            nums = [float(v) for v in vals if v is not None]
            scored.append((sid, sum(nums) / len(nums) if nums else 0))
        scored.sort(key=lambda x: -x[1])
        top_s = [s[0] for s in scored[:40]]
        mat = [[pivot.get(s, {}).get(c) for c in cohort_ids] for s in top_s]
        fig_h = _heatmap(top_s, cohort_ids, mat, "戦略 × コホート（Median PF · Top 40）")
        sections.append("<section id='cohort'><h2>🏢 市場区分・コホート比較</h2>")
        sections.append(fig_to_html_block(fig_h, include_plotlyjs=False, div_id="chart_cohort"))
        sections.append("</section>")

    if lab:
        cells = lab.get("cells") or []
        cohort_ids = sorted({c["cohort_id"] for c in cells})
        rule_ids = sorted({c["rule_id"] for c in cells})
        pivot_l: dict[str, dict[str, float | None]] = {}
        for c in cells:
            exp = (c.get("overview") or c.get("summary") or {}).get("expectancy_pct")
            pivot_l.setdefault(c["rule_id"], {})[c["cohort_id"]] = exp
        mat = [[pivot_l.get(r, {}).get(c) for c in cohort_ids] for r in rule_ids]
        fig_l = _heatmap(rule_ids, cohort_ids, mat, "イザナミラボ · 期待値%（ルール × コホート）")
        sections.append("<section id='lab'><h2>🔬 イザナミラボ ルール</h2>")
        sections.append(fig_to_html_block(fig_l, include_plotlyjs=False, div_id="chart_lab"))
        sections.append("</section>")

    if not sections:
        sections.append(
            '<p class="muted">データがありません。先に <code>uv run signalforge hub build</code> を実行してください。</p>'
        )

    body = "\n".join(sections)
    html = wrap_page(
        title="検証結果ハブ",
        subtitle="全戦略・全コホート・ラボルールのランキングとヒートマップ",
        body=body,
        generated=generated,
        nav_active="hub",
    )
    # Inject extra nav link style for hub-only page
    html = html.replace(BASE_CSS, BASE_CSS + "\nsection { scroll-margin-top: 1rem; }\n")

    out = _hub_dir() / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


def write_manifest(info: dict[str, Any]) -> None:
    path = _hub_dir() / "manifest.json"
    path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
