"""Unified static site export — hub, paper, backtest comparison, strategy guides."""

from __future__ import annotations

import warnings
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.config import load_style_config
from signalforge.optimize.spaces import build_cfg_override, strategies_for_style
from signalforge.paper.matrix import PAPER_SIMULATIONS, STYLE_LABELS
from signalforge.pipeline import run_backtest_pipeline
from signalforge.report.charts import plot_strategy_comparison
from signalforge.report.dashboard_components import oos_metrics_from_trades
from signalforge.report.dashboard_strategies import STRATEGY_GUIDES, STRATEGY_LABELS
from signalforge.report.static_dashboard import export_paper_page, paper_summary_row
from signalforge.report.static_html import fig_to_html_block, wrap_page
from signalforge.report.strategy_visuals import plot_strategy_demo

MACD_OPTIMIZED = {
    "adx_threshold": 23,
    "ema_trend": 200,
    "long_only": True,
    "atr_tp_multiple": 2.0,
    "atr_sl_multiple": 1.5,
}

BACKTEST_STYLES = ("swing", "swing_high_winrate", "daytrade")


def _run_backtest_row(style: str, strategy: str) -> dict[str, Any] | None:
    ml_filter = style == "swing_high_winrate"
    cfg_override = None
    if strategy == "macd_cross" and style != "swing_high_winrate":
        cfg_override = build_cfg_override("macd_cross", MACD_OPTIMIZED, load_style_config(style))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=PendingDeprecationWarning)
            result = run_backtest_pipeline(
                style,
                strategy,
                ml_filter=ml_filter,
                cost_model="alpaca",
                cfg_override=cfg_override,
                refresh_data=False,
            )
    except Exception as exc:
        return {"style": style, "strategy": strategy, "error": str(exc)}

    trades = result["trades"]
    if ml_filter and not trades.empty and "is_oos" in trades.columns:
        m = oos_metrics_from_trades(trades, result["equity"])
        scope = "OOS"
    else:
        m = result["metrics"]
        scope = "全期間"
    return {
        "style": style,
        "strategy": strategy,
        "style_label": STYLE_LABELS.get(style, style),
        "strategy_label": STRATEGY_LABELS.get(strategy, strategy),
        "scope": scope,
        "profit_factor": m.get("profit_factor", 0),
        "win_rate": m.get("win_rate", 0),
        "sharpe": m.get("sharpe", 0),
        "total_trades": m.get("total_trades", 0),
        "max_drawdown_pct": m.get("max_drawdown_pct", 0),
        "total_return_pct": m.get("total_return_pct", 0),
    }


def collect_backtest_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for style in BACKTEST_STYLES:
        for strategy in strategies_for_style(style):
            row = _run_backtest_row(style, strategy)
            if row:
                rows.append(row)
    return rows


def export_strategy_guide(output_dir: Path, strategy_key: str) -> Path:
    guide = STRATEGY_GUIDES[strategy_key]
    fig = plot_strategy_demo(strategy_key)
    chart_html = ""
    if fig is not None:
        chart_html = fig_to_html_block(fig, include_plotlyjs="cdn", div_id="strategy-demo")

    def _list_items(items: list[str]) -> str:
        return "<ul class='compact'>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"

    sell_block = ""
    if guide.get("signal_sell"):
        sell_block = f'<p class="negative"><strong>🔴 売り:</strong> {escape(guide["signal_sell"])}</p>'
    else:
        sell_block = '<p class="muted">🔴 売りシグナル: なし（買い専用）</p>'

    params_html = _list_items([f"{k}: {v}" for k, v in guide["params"].items()])
    pros_html = _list_items(guide["pros"])
    cons_html = _list_items(guide["cons"])

    body = f"""
    <div class="info-box">{escape(guide["summary"])}</div>
    <section><h2>考え方</h2><p>{escape(guide["concept"])}</p></section>
    <div class="grid-2">
      <section><h2>🟢 買いシグナル</h2><p>{escape(guide.get("signal_buy", "—"))}</p>{_list_items(guide["entry_long"])}</section>
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
    <section><h2>🎯 向いている相場</h2><p>{escape(guide["market"])}</p></section>
    <section><h2>💡 使い方</h2><p>{escape(guide["tips"])}</p></section>
    """

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
            body += (
                "<tr>"
                f"<td>{escape(r.get('style_label', r.get('style', '')))}</td>"
                f"<td>{escape(r.get('strategy_label', r.get('strategy', '')))}</td>"
                f"<td>${float(r.get('equity', 0)):,.0f}</td>"
                f'<td class="{ret_cls}">{ret:+.2f}%</td>'
                f"<td>{float(r.get('win_rate', 0)):.1%}</td>"
                f"<td>{float(r.get('profit_factor', 0)):.2f}</td>"
                f"<td>{r.get('total_trades', 0)}</td>"
                f'<td><a href="{escape(r.get("href", "#"))}">詳細</a></td>'
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
) -> Path:
    # PF comparison chart (backtest, swing only for clarity)
    swing_bt = [r for r in backtest_rows if r.get("style") == "swing" and not r.get("error")]
    chart_html = ""
    if swing_bt:
        fig = plot_strategy_comparison(swing_bt, metric="profit_factor")
        chart_html = fig_to_html_block(fig, include_plotlyjs="cdn", div_id="bt-compare")

    guide_links = "".join(
        f'<a href="guide/{k}.html">{escape(STRATEGY_LABELS[k])}</a> '
        for k in STRATEGY_GUIDES
    )

    body = f"""
    <div class="info-box">
      NVDA 向けテクニカル分析ダッシュボード（ローカル Streamlit 版と同等の比較・解説を静的サイト化）。
      Paper = フォワード仮想運用、バックテスト = 全期間（または OOS）シミュレーション。
    </div>

    <section id="paper">
      <h2>📈 Paper Trading — 全戦略フォワード成績</h2>
      <p class="muted">各戦略 $100,000 独立口座 · 毎日自動更新</p>
      {_comparison_table(paper_rows, kind="paper")}
    </section>

    <section id="backtest">
      <h2>⚖️ バックテスト — 戦略比較</h2>
      <p class="muted">Alpaca コストモデル · swing_high_winrate は ML フィルタ OOS</p>
      {chart_html}
      {_comparison_table(backtest_rows, kind="backtest")}
    </section>

    <section id="guides">
      <h2>📚 戦略解説（6 戦略）</h2>
      <p>{guide_links}</p>
    </section>
    """

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title="SignalForge Dashboard",
        subtitle="NVDA マルチ戦略分析 — Paper · バックテスト · 戦略解説",
        body=body,
        generated=generated,
        nav_active="hub",
        depth=0,
    )
    path = output_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def export_full_site(output_dir: Path, *, refresh: bool = False) -> Path:
    """Build complete GitHub Pages site."""
    output_dir.mkdir(parents=True, exist_ok=True)

    paper_rows: list[dict] = []
    for style, strategy in PAPER_SIMULATIONS:
        export_paper_page(output_dir, style, strategy, refresh=refresh, depth=1)
        row = paper_summary_row(style, strategy, refresh=refresh)
        if row:
            paper_rows.append(row)

    for strategy_key in STRATEGY_GUIDES:
        export_strategy_guide(output_dir, strategy_key)

    backtest_rows = collect_backtest_rows()
    hub = export_hub(output_dir, paper_rows, backtest_rows)
    (output_dir / ".nojekyll").touch()
    return hub
