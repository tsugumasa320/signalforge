"""Build a static HTML paper-trading dashboard for GitHub Pages."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.backtest.metrics import compute_metrics
from signalforge.paper.portfolio import PaperPortfolio
from signalforge.paper.runner import _prepare_dataframe
from signalforge.report.charts import plot_equity_and_drawdown, plot_price_and_trades, plot_trade_pnl
from signalforge.config import load_style_config


def export_paper_dashboard(
    output_dir: Path,
    style: str = "swing",
    strategy: str | None = None,
    *,
    refresh: bool = False,
) -> Path:
    """Write ``index.html`` (+ ``.nojekyll``) for GitHub Pages."""
    cfg = load_style_config(style)
    strategy = strategy or cfg.get("strategy", "ema_pullback")

    portfolio = PaperPortfolio.load(style, strategy)
    if portfolio is None:
        raise RuntimeError(f"Paper 口座がありません: {style}/{strategy}")

    df, data_source = _prepare_dataframe(style, cfg, refresh)
    if df.empty:
        raise RuntimeError("OHLCV データがありません。")

    start_ts = pd.Timestamp(portfolio.last_processed_bar or portfolio.started_at)
    if start_ts.tzinfo is None and df.index.tz is not None:
        start_ts = start_ts.tz_localize("UTC")
    paper_df = df[df.index >= start_ts].copy()
    if paper_df.empty:
        paper_df = df.tail(min(120, len(df))).copy()

    closed = pd.DataFrame(portfolio.closed_trades)
    if not closed.empty:
        for col in ("entry_time", "exit_time"):
            if col in closed.columns:
                closed[col] = pd.to_datetime(closed[col])

    eq = pd.Series(
        [s["equity"] for s in portfolio.equity_snapshots],
        index=pd.to_datetime([s["date"] for s in portfolio.equity_snapshots]),
    )
    metrics = compute_metrics(closed, eq)
    last_close = float(df.iloc[-1]["close"])
    equity = portfolio.mark_to_market_equity(last_close)
    total_return = (equity / portfolio.initial_cash - 1) * 100 if portfolio.initial_cash else 0.0

    title = f"SignalForge Paper — {style} / {strategy}"
    charts = [
        plot_equity_and_drawdown(eq, title="評価額 & ドローダウン"),
        plot_price_and_trades(paper_df, closed, title="価格 & トレード（Paper 期間）"),
        plot_trade_pnl(closed, title="トレード別 PnL %"),
    ]

    chart_html = ""
    plotly_js = "cdn"
    for i, fig in enumerate(charts):
        chart_html += fig.to_html(
            full_html=False,
            include_plotlyjs=plotly_js if i == 0 else False,
            config={"displayModeBar": False},
            div_id=f"chart-{i}",
        )
        plotly_js = False

    position_html = "なし"
    if portfolio.position:
        pos = portfolio.position
        position_html = (
            f"{escape(str(pos.get('side', '?')))} @ "
            f"{float(pos.get('entry_price', 0)):.2f} "
            f"({escape(str(pos.get('entry_time', '')))})"
        )

    trades_rows = ""
    if not closed.empty:
        for _, row in closed.iterrows():
            trades_rows += (
                "<tr>"
                f"<td>{escape(str(row.get('side', '')))}</td>"
                f"<td>{escape(str(row.get('entry_time', '')))}</td>"
                f"<td>{escape(str(row.get('exit_time', '')))}</td>"
                f"<td>{float(row.get('pnl_pct', 0)):+.2f}%</td>"
                f"<td>{escape(str(row.get('reason', '')))}</td>"
                "</tr>"
            )
    else:
        trades_rows = '<tr><td colspan="5" class="muted">まだクローズドトレードはありません</td></tr>'

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = _PAGE_TEMPLATE.format(
        title=escape(title),
        style=escape(style),
        strategy=escape(strategy),
        data_source=escape(data_source),
        last_bar=escape(str(df.index[-1])),
        last_run=escape(str(portfolio.last_run_at or "—")),
        generated=generated,
        equity=f"{equity:,.0f}",
        total_return=f"{total_return:+.2f}",
        win_rate=f"{metrics.get('win_rate', 0):.1%}",
        profit_factor=f"{metrics.get('profit_factor', 0):.2f}",
        total_trades=str(metrics.get("total_trades", 0)),
        cash=f"{portfolio.cash:,.0f}",
        position=position_html,
        chart_html=chart_html,
        trades_rows=trades_rows,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    index = output_dir / "index.html"
    index.write_text(html, encoding="utf-8")
    (output_dir / ".nojekyll").touch()
    return index


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card: #1e293b;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #3b82f6;
      --green: #22c55e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    header {{
      padding: 1.5rem 2rem;
      border-bottom: 1px solid #334155;
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    }}
    header h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; }}
    header p {{ margin: 0; color: var(--muted); font-size: 0.9rem; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 1.5rem; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1.5rem;
    }}
    .metric {{
      background: var(--card);
      border-radius: 8px;
      padding: 1rem;
      border: 1px solid #334155;
    }}
    .metric label {{ display: block; font-size: 0.75rem; color: var(--muted); text-transform: uppercase; }}
    .metric value {{ display: block; font-size: 1.35rem; font-weight: 600; margin-top: 0.25rem; }}
    .metric.positive value {{ color: var(--green); }}
    section {{
      background: var(--card);
      border-radius: 8px;
      padding: 1rem;
      margin-bottom: 1rem;
      border: 1px solid #334155;
    }}
    section h2 {{ margin: 0 0 0.75rem; font-size: 1rem; color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
    th, td {{ padding: 0.5rem; text-align: left; border-bottom: 1px solid #334155; }}
    th {{ color: var(--muted); font-weight: 500; }}
    .muted {{ color: var(--muted); }}
    footer {{ text-align: center; padding: 2rem; color: var(--muted); font-size: 0.8rem; }}
    a {{ color: var(--accent); }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p>データ: {data_source}  |  最終足: {last_bar}  |  最終実行: {last_run}</p>
  </header>
  <main>
    <div class="metrics">
      <div class="metric"><label>評価額</label><value>${equity}</value></div>
      <div class="metric positive"><label>総リターン</label><value>{total_return}%</value></div>
      <div class="metric"><label>Win率</label><value>{win_rate}</value></div>
      <div class="metric"><label>PF</label><value>{profit_factor}</value></div>
      <div class="metric"><label>トレード数</label><value>{total_trades}</value></div>
      <div class="metric"><label>現金</label><value>${cash}</value></div>
    </div>
    <section>
      <h2>建玉</h2>
      <p>{position}</p>
    </section>
    {chart_html}
    <section>
      <h2>クローズドトレード</h2>
      <table>
        <thead><tr><th>Side</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr></thead>
        <tbody>{trades_rows}</tbody>
      </table>
    </section>
  </main>
  <footer>
    Generated {generated} ·
    <a href="https://github.com/tsugumasa320/signalforge">SignalForge</a>
  </footer>
</body>
</html>
"""
