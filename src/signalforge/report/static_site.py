"""Unified static site export — hub, paper, backtest comparison, strategy guides."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.config import load_web_catalog
from signalforge.paper.diversified import list_diversified_paper_books
from signalforge.paper.diversified_specs import DIVERSIFIED_PAPER_SIMULATIONS
from signalforge.paper.matrix import PAPER_SIMULATIONS, STYLE_LABELS
from signalforge.report.charts import plot_strategy_comparison
from signalforge.report.metrics_ja import EXPECTANCY, PROFIT_FACTOR
from signalforge.report.static_dashboard import (
    diversified_paper_summary_row,
    export_diversified_paper_page,
    export_paper_page,
    paper_summary_row,
)
from signalforge.report.static_html import fig_to_html_block, wrap_page
from signalforge.report.strategy_guide_builder import resolve_strategy_guide, strategy_display_title
from signalforge.report.strategy_visuals import plot_strategy_demo


def collect_tse_experiment_rows(*, top_n: int = 133) -> list[dict[str, Any]]:
    """Precomputed TSE campaign (median metrics per strategy), same source as Streamlit ranking."""
    from signalforge.experiments.scan import scan_campaign_progress

    scan = scan_campaign_progress(fast=True)
    rows: list[dict[str, Any]] = []
    for r in scan.get("complete") or []:
        sid = str(r.get("strategy_id") or "")
        if not sid:
            continue
        style = str(r.get("style") or "swing")
        rows.append(
            {
                "style": style,
                "strategy": sid,
                "style_label": STYLE_LABELS.get(style, style),
                "strategy_label": strategy_display_title(sid),
                "scope": "TSE3521·中央値",
                "expectancy_pct": r.get("expectancy_pct"),
                "profit_factor": r.get("profit_factor"),
                "win_rate": r.get("win_rate"),
                "total_trades": r.get("total_trades"),
                "max_drawdown_pct": r.get("max_drawdown_pct"),
                "n_tickers": r.get("n_tickers"),
            }
        )
    rows.sort(
        key=lambda x: (x.get("expectancy_pct") is None, -(float(x["expectancy_pct"]) if x.get("expectancy_pct") is not None else -1e9)),
    )
    return rows[:top_n] if top_n > 0 else rows


def hub_guide_strategy_ids(tse_rows: list[dict[str, Any]], *, top_n: int = 40) -> list[str]:
    """Guides on Pages: forward matrix + top TSE strategies (not full harvest catalog)."""
    ids: set[str] = {spec.strategy for spec in DIVERSIFIED_PAPER_SIMULATIONS}
    for r in tse_rows[:top_n]:
        ids.add(str(r["strategy"]))
    return sorted(ids)


def _implemented_catalog_ids() -> list[str]:
    return sorted(
        str(s["id"])
        for s in load_web_catalog().get("strategies", [])
        if s.get("implemented") and s.get("id")
    )


def export_strategy_guide(output_dir: Path, strategy_key: str) -> Path:
    guide = resolve_strategy_guide(strategy_key)
    fig = plot_strategy_demo(strategy_key)
    chart_html = ""
    if fig is not None:
        chart_html = fig_to_html_block(fig, include_plotlyjs="cdn", div_id="strategy-demo")

    def _esc(text: object) -> str:
        return escape(str(text) if text is not None else "")

    def _list_items(items: list[str]) -> str:
        return "<ul class='compact'>" + "".join(f"<li>{_esc(i)}</li>" for i in items if i) + "</ul>"

    sell_block = ""
    if guide.get("signal_sell"):
        sell_block = f'<p class="negative"><strong>🔴 売り:</strong> {_esc(guide["signal_sell"])}</p>'
    else:
        sell_block = '<p class="muted">🔴 売りシグナル: なし（買い専用）</p>'

    params_html = _list_items([f"{k}: {v}" for k, v in guide["params"].items()])
    pros_html = _list_items(guide["pros"])
    cons_html = _list_items(guide["cons"])

    body = f"""
    <div class="info-box">{_esc(guide.get("summary"))}</div>
    <section><h2>考え方</h2><p>{_esc(guide.get("concept"))}</p></section>
    <div class="grid-2">
      <section><h2>🟢 買いシグナル</h2><p>{_esc(guide.get("signal_buy") or "—")}</p>{_list_items(guide["entry_long"])}</section>
      <section><h2>🔴 売りシグナル</h2>{sell_block}{_list_items(guide.get("entry_short", [])) if guide.get("entry_short") else ""}</section>
    </div>
    {chart_html}
    <div class="grid-2">
      <section><h2>🚪 イグジット</h2>{_list_items(guide["exit"])}</section>
      <section><h2>⚙️ パラメータ</h2>{params_html}</section>
    </div>
    <div class="grid-2">
      <section><h2>✅ 長所</h2>{pros_html}</section>
      <section><h2>⚠️ 短所</h2>{cons_html}</section>
    </div>
    <section><h2>🎯 向いている相場</h2><p>{_esc(guide.get("market"))}</p></section>
    <section><h2>💡 使い方</h2><p>{_esc(guide.get("tips"))}</p></section>
    """
    sources = guide.get("sources") or []
    if sources:
        src_items = []
        for src in sources[:30]:
            title = escape(str(src.get("title") or src.get("url") or "—"))
            url = src.get("url")
            if url:
                src_items.append(f'<li><a href="{escape(str(url))}">{title}</a></li>')
            else:
                src_items.append(f"<li>{title}</li>")
        body += f"<section><h2>参考ソース</h2><ul class='compact'>{''.join(src_items)}</ul></section>"

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title=f"戦略解説 — {guide['title']}",
        subtitle=f"{guide['style']}  |  キー: `{strategy_key}`",
        body=body,
        generated=generated,
        nav_active="guides",
        depth=1,
    )
    guide_dir = output_dir / "guide"
    guide_dir.mkdir(parents=True, exist_ok=True)
    path = guide_dir / f"{strategy_key}.html"
    path.write_text(html, encoding="utf-8")
    return path


def _comparison_table(rows: list[dict], *, kind: str) -> str:
    if not rows:
        return '<p class="muted">データがありません。</p>'

    if kind == "paper":
        header = (
            "<tr><th>スタイル</th><th>戦略</th><th>評価額</th><th>リターン</th>"
            "<th>Win率</th><th>PF</th><th>トレード</th><th>詳細</th></tr>"
        )
        body = ""
        for r in rows:
            if r.get("error"):
                continue
            ret = float(r.get("total_return_pct", 0))
            ret_cls = "positive" if ret >= 0 else "negative"
            if r.get("currency") == "JPY":
                eq_s = f"¥{float(r.get('equity', 0)):,.0f}"
            else:
                eq_s = f"${float(r.get('equity', 0)):,.0f}"
            body += (
                "<tr>"
                f"<td>{escape(r.get('style_label', r.get('style', '')))}</td>"
                f"<td>{escape(r.get('strategy_label', r.get('strategy', '')))}</td>"
                f"<td>{eq_s}</td>"
                f'<td class="{ret_cls}">{ret:+.2f}%</td>'
                f"<td>{float(r.get('win_rate', 0)):.1%}</td>"
                f"<td>{float(r.get('profit_factor', 0)):.2f}</td>"
                f"<td>{r.get('total_trades', 0)}</td>"
                f'<td><a href="{escape(r.get("href", "#"))}">詳細</a></td>'
                "</tr>"
            )
    elif kind == "tse":
        header = (
            f"<tr><th>スタイル</th><th>戦略</th><th>集計</th><th>{escape(EXPECTANCY)}</th>"
            f"<th>{escape(PROFIT_FACTOR)}</th><th>Win率</th><th>MaxDD</th><th>取引数</th><th>解説</th></tr>"
        )
        body = ""
        for r in rows:
            strat = str(r.get("strategy") or "")
            exp = r.get("expectancy_pct")
            exp_s = f"{float(exp):+.3f}" if exp is not None and exp == exp else "—"
            exp_cls = "positive" if exp is not None and float(exp) > 0 else "negative" if exp is not None and float(exp) < 0 else ""
            pf = r.get("profit_factor")
            pf_s = f"{float(pf):.2f}" if pf is not None and pf == pf else "—"
            wr = r.get("win_rate")
            wr_s = f"{float(wr):.1%}" if wr is not None and wr == wr else "—"
            dd = r.get("max_drawdown_pct")
            dd_s = f"{float(dd):.2f}%" if dd is not None and dd == dd else "—"
            body += (
                "<tr>"
                f"<td>{escape(r.get('style_label', ''))}</td>"
                f"<td>{escape(r.get('strategy_label', strat))}</td>"
                f"<td><span class='badge'>{escape(r.get('scope', ''))}</span></td>"
                f'<td class="{exp_cls}">{exp_s}</td>'
                f"<td>{pf_s}</td>"
                f"<td>{wr_s}</td>"
                f"<td>{dd_s}</td>"
                f"<td>{r.get('total_trades', '—')}</td>"
                f'<td><a href="guide/{escape(strat)}.html">解説</a></td>'
                "</tr>"
            )
    else:
        header = (
            "<tr><th>スタイル</th><th>戦略</th><th>スコープ</th><th>PF</th>"
            "<th>Win率</th><th>Sharpe</th><th>MaxDD</th><th>リターン</th><th>解説</th></tr>"
        )
        body = ""
        for r in rows:
            if r.get("error"):
                body += (
                    "<tr>"
                    f"<td>{escape(r.get('style_label', ''))}</td>"
                    f"<td>{escape(r.get('strategy_label', r.get('strategy', '')))}</td>"
                    f'<td colspan="7" class="muted">{escape(r.get("error", "エラー"))}</td>'
                    "</tr>"
                )
                continue
            ret = float(r.get("total_return_pct", 0))
            ret_cls = "positive" if ret >= 0 else "negative"
            strat = r.get("strategy", "")
            body += (
                "<tr>"
                f"<td>{escape(r.get('style_label', ''))}</td>"
                f"<td>{escape(r.get('strategy_label', strat))}</td>"
                f"<td><span class='badge'>{escape(r.get('scope', ''))}</span></td>"
                f"<td>{float(r.get('profit_factor', 0)):.2f}</td>"
                f"<td>{float(r.get('win_rate', 0)):.1%}</td>"
                f"<td>{float(r.get('sharpe', 0)):.2f}</td>"
                f"<td>{float(r.get('max_drawdown_pct', 0)):.2f}%</td>"
                f'<td class="{ret_cls}">{ret:+.2f}%</td>'
                f'<td><a href="guide/{escape(strat)}.html">解説</a></td>'
                "</tr>"
            )

    return f"<table><thead>{header}</thead><tbody>{body}</tbody></table>"


def export_hub(
    output_dir: Path,
    paper_rows: list[dict],
    backtest_rows: list[dict],
    diversified_rows: list[dict] | None = None,
) -> Path:
    chart_html = ""
    top_chart = [
        r
        for r in backtest_rows[:25]
        if r.get("profit_factor") is not None and r.get("profit_factor") == r.get("profit_factor")
    ]
    if top_chart:
        chart_payload = [
            {"strategy": str(r.get("strategy_label", r.get("strategy")))[:48], "profit_factor": float(r["profit_factor"])}
            for r in top_chart
        ]
        fig = plot_strategy_comparison(chart_payload, metric="profit_factor")
        chart_html = fig_to_html_block(fig, include_plotlyjs="cdn", div_id="bt-compare")

    guide_ids = hub_guide_strategy_ids(backtest_rows) if backtest_rows else []
    guide_links = "".join(
        f'<a href="guide/{k}.html">{escape(strategy_display_title(k))}</a> '
        for k in guide_ids[:40]
    )
    if len(guide_ids) > 40:
        guide_links += f'<span class="muted"> …他 {len(guide_ids) - 40} 件（guide/ 配下）</span>'

    body = f"""
    <div class="info-box">
      日本株向けテクニカル分析ダッシュボード（ローカル Streamlit 版と同等の比較・解説を静的サイト化）。
      Paper = TSE 分散フォワード。バックテスト表 = 保存済み TSE 実験（3521銘柄・典型値）。
    </div>

    <section id="paper">
      <h2>📈 Paper Trading — フォワード成績</h2>
      <p class="muted">GitHub Pages は Actions 日次更新（JST 朝頃）後が最新</p>
      <h3>1口座 · 分散（TSE · 実運用近似）</h3>
      <p class="muted">¥300万 · 同時5 · 20%/回 · 先着 — <code>data/paper/diversified_*.json</code> がある場合のみ</p>
      {_comparison_table(diversified_rows or [], kind="paper")}
    </section>

    <section id="backtest">
      <h2>⚖️ TSE 実験 — 戦略比較（事前バックテスト）</h2>
      <p class="muted">japan コスト · 各列は全銘柄BTの中央値（Streamlit TSE 実験タブと同系）</p>
      {chart_html}
      {_comparison_table(backtest_rows, kind="tse")}
    </section>

    <section id="guides">
      <h2>📚 戦略解説（{len(guide_ids)} 戦略）</h2>
      <p>{guide_links}</p>
    </section>
    """

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title="SignalForge Dashboard",
        subtitle="日本株マルチ戦略分析 — Paper · バックテスト · 戦略解説",
        body=body,
        generated=generated,
        nav_active="hub",
        depth=0,
    )
    path = output_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def export_guides_index(output_dir: Path, *, guide_ids: list[str] | None = None) -> Path:
    guide_ids = guide_ids if guide_ids is not None else _implemented_catalog_ids()
    links = "".join(
        f'<li><a href="{gid}.html">{escape(strategy_display_title(gid))}</a> '
        f'<span class="muted">({gid})</span></li>'
        for gid in guide_ids
    )
    body = f"<section><h1>戦略解説一覧</h1><ul class='compact'>{links}</ul></section>"
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title="戦略解説一覧",
        subtitle=f"{len(guide_ids)} 戦略",
        body=body,
        generated=generated,
        nav_active="guides",
        depth=1,
    )
    guide_dir = output_dir / "guide"
    guide_dir.mkdir(parents=True, exist_ok=True)
    path = guide_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def export_guides_only(output_dir: Path) -> Path:
    """Export strategy guide HTML only (fast CI / docs refresh)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for strategy_key in _implemented_catalog_ids():
        export_strategy_guide(output_dir, strategy_key)
    (output_dir / ".nojekyll").touch()
    return export_guides_index(output_dir)


def export_full_site(output_dir: Path, *, refresh: bool = False, guides_only: bool = False) -> Path:
    """Build complete GitHub Pages site."""
    if guides_only:
        return export_guides_only(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    for sub, keep_prefix in (("guide", None), ("paper", "diversified_")):
        d = output_dir / sub
        if not d.is_dir():
            continue
        for path in d.glob("*.html"):
            if keep_prefix and path.name.startswith(keep_prefix):
                continue
            path.unlink(missing_ok=True)

    paper_rows: list[dict] = []
    for style, strategy in PAPER_SIMULATIONS:
        export_paper_page(output_dir, style, strategy, refresh=refresh, depth=1)
        row = paper_summary_row(style, strategy, refresh=refresh)
        if row:
            paper_rows.append(row)

    diversified_rows: list[dict] = []
    for book in list_diversified_paper_books():
        export_diversified_paper_page(output_dir, book, depth=1, refresh=refresh)
        diversified_rows.append(diversified_paper_summary_row(book))

    backtest_rows = collect_tse_experiment_rows()
    guide_ids = hub_guide_strategy_ids(backtest_rows)
    for strategy_key in guide_ids:
        export_strategy_guide(output_dir, strategy_key)
    export_guides_index(output_dir, guide_ids=guide_ids)

    hub = export_hub(output_dir, paper_rows, backtest_rows, diversified_rows)
    (output_dir / ".nojekyll").touch()
    return hub
