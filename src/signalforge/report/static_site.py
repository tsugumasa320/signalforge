"""Unified static site export — hub, paper, backtest comparison, strategy guides."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
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


@lru_cache(maxsize=1)
def _tse_summary_doc() -> dict[str, Any]:
    """Live curated summary when experiment data exists locally, else the committed snapshot (CI)."""
    from signalforge.experiments.curation import build_published_summary, load_published_summary
    from signalforge.experiments.scan import scan_campaign_progress

    if scan_campaign_progress(fast=True).get("complete"):
        return build_published_summary()
    return load_published_summary()


def collect_tse_experiment_rows(*, top_n: int = 0) -> list[dict[str, Any]]:
    """Curated TSE campaign rows (duplicates merged, proxy BT hidden), ranked by 1-account return."""
    doc = _tse_summary_doc()
    rows: list[dict[str, Any]] = []
    for r in doc.get("rows") or []:
        sid = str(r.get("strategy_id") or "")
        if not sid:
            continue
        style = str(r.get("style") or "swing")
        port = r.get("portfolio") or {}
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
                "aliases": r.get("aliases") or [],
                "portfolio_return_pct": port.get("total_return_pct"),
                "portfolio_is_pct": port.get("is_return_pct"),
                "portfolio_oos_pct": port.get("oos_return_pct"),
                "portfolio_dd_pct": port.get("max_drawdown_pct"),
            }
        )

    def _key(x: dict[str, Any]) -> tuple:
        pr = x.get("portfolio_return_pct")
        exp = x.get("expectancy_pct")
        return (pr is None, -(float(pr) if pr is not None else 0.0), -(float(exp) if exp is not None else -1e9))

    rows.sort(key=_key)
    return rows[:top_n] if top_n > 0 else rows


def tse_curation_note() -> str:
    doc = _tse_summary_doc()
    info = doc.get("curation") or {}
    params = doc.get("portfolio_params") or {}
    if not info:
        return ""
    rule = ""
    if params.get("entry_priority"):
        rule = (
            f"1口座列: ¥{float(params.get('initial_capital') or 0):,.0f} · 同時{params.get('max_positions')} · "
            f"売買代金 ≥ ¥{float(params.get('min_turnover_jpy') or 0) / 1e8:.0f}億 · "
            f"シグナル集中日（過去1年の上位{(1 - float(params.get('min_breadth_rank') or 0)) * 100:.0f}%）のみ · "
            f"売買代金順。前半=〜{params.get('oos_start', '2024-01-01')}、後半=以降。"
        )
    return (
        f"掲載 {info.get('n_visible')} / {info.get('n_input')} 戦略 — "
        f"同一結果の重複 {len(info.get('merged_duplicates') or [])} 件を統合、"
        f"代理BT・データ未取得 {len(info.get('hidden_untrusted') or [])} 件は非掲載。{rule}"
    )


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


def _intraday_table() -> str:
    from signalforge.experiments.intraday_campaign import intraday_result_rows
    from signalforge.report.strategy_guide_builder import strategy_display_title

    rows = intraday_result_rows()
    if not rows:
        return '<p class="muted">短期足の結果はまだありません。</p>'
    body = ""
    for row in rows:
        ret = row.get("median_return_pct")
        pf = row.get("median_profit_factor")
        trades = row.get("median_trades")
        try:
            ret_s = f"{float(ret):+.2f}%" if ret is not None else "—"
        except (TypeError, ValueError):
            ret_s = "—"
        try:
            pf_s = f"{float(pf):.2f}" if pf is not None else "—"
        except (TypeError, ValueError):
            pf_s = "—"
        trades_s = "—" if trades is None else f"{float(trades):.0f}"
        body += (
            "<tr>"
            f"<td>{escape(row['timeframe_label'])}</td>"
            f"<td>{escape(strategy_display_title(row['strategy_id']))}</td>"
            f"<td>{escape(row['status'])}</td>"
            f"<td>{escape(str(row.get('window') or '—'))}</td>"
            f"<td>{ret_s}</td>"
            f"<td>{pf_s}</td>"
            f"<td>{trades_s}</td>"
            "</tr>"
        )
    header = (
        "<tr><th>足</th><th>戦略</th><th>状態</th><th>期間</th>"
        "<th>中央リターン</th><th>中央PF</th><th>中央トレード数</th></tr>"
    )
    return f"<table><thead>{header}</thead><tbody>{body}</tbody></table>"


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
            "<tr><th>戦略</th><th>1口座リターン</th><th>前半</th><th>後半</th><th>1口座DD</th>"
            f"<th>{escape(EXPECTANCY)}（中央値）</th><th>{escape(PROFIT_FACTOR)}</th><th>Win率</th>"
            "<th>取引数</th><th>同一結果</th><th>解説</th></tr>"
        )

        def _num(v: Any) -> float | None:
            return float(v) if v is not None and v == v else None

        def _pct_cell(v: Any, digits: int = 1) -> str:
            x = _num(v)
            if x is None:
                return "<td>—</td>"
            cls = "positive" if x > 0 else "negative" if x < 0 else ""
            return f'<td class="{cls}">{x:+.{digits}f}%</td>'

        body = ""
        for r in rows:
            strat = str(r.get("strategy") or "")
            pf = _num(r.get("profit_factor"))
            wr = _num(r.get("win_rate"))
            dd = _num(r.get("portfolio_dd_pct"))
            aliases = r.get("aliases") or []
            alias_s = (
                f"<span class='muted' title='{escape(', '.join(aliases))}'>他{len(aliases)}</span>" if aliases else ""
            )
            body += (
                "<tr>"
                f"<td>{escape(r.get('strategy_label', strat))}<br><span class='muted'>{escape(strat)}</span></td>"
                f"{_pct_cell(r.get('portfolio_return_pct'))}"
                f"{_pct_cell(r.get('portfolio_is_pct'))}"
                f"{_pct_cell(r.get('portfolio_oos_pct'))}"
                f"<td>{f'{dd:.1f}%' if dd is not None else '—'}</td>"
                f"{_pct_cell(r.get('expectancy_pct'), 3)}"
                f"<td>{f'{pf:.2f}' if pf is not None else '—'}</td>"
                f"<td>{f'{wr:.1%}' if wr is not None else '—'}</td>"
                f"<td>{r.get('total_trades', '—')}</td>"
                f"<td>{alias_s}</td>"
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
      <p class="muted">GitHub Pages は Actions 日次更新（JST 18:17）後が最新</p>
      <h3>1口座 · 分散（TSE · 実運用近似）</h3>
      <p class="muted">¥300万 · 同時5 · 20%/回 · 売買代金 ≥ 5億円 · シグナル集中日のみ · 売買代金順 · 同業種2まで</p>
      {_comparison_table(diversified_rows or [], kind="paper")}
    </section>

    <section id="intraday">
      <h2>⏱ 短期足の実験</h2>
      <p class="muted">5分足は約60日、1分足は約7日。数字は全銘柄の中央値です。</p>
      {_intraday_table()}
    </section>

    <section id="backtest">
      <h2>⚖️ 日足の実験 — 戦略比較（事前バックテスト）</h2>
      <p class="muted">日足 · japan コスト · 1口座列 = 実運用ルールでの全期間シミュレーション（並び順）· 中央値列 = 全銘柄BTの典型値。5分足と1分足は上の表。</p>
      <p class="muted">{escape(tse_curation_note())}</p>
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
