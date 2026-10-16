"""Build a static HTML paper-trading page."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pandas as pd

from signalforge.backtest.metrics import compute_metrics
from signalforge.config import load_style_config
from signalforge.paper.matrix import STYLE_LABELS
from signalforge.paper.portfolio import PaperPortfolio
from signalforge.paper.runner import _prepare_dataframe
from signalforge.report.charts import plot_equity_and_drawdown, plot_price_and_trades, plot_trade_pnl
from signalforge.report.dashboard_strategies import STRATEGY_LABELS
from signalforge.report.static_html import fig_to_html_block, wrap_page


def _paper_summary(portfolio: PaperPortfolio, df: pd.DataFrame) -> dict:
    closed = pd.DataFrame(portfolio.closed_trades)
    if not closed.empty:
        for col in ("entry_time", "exit_time"):
            if col in closed.columns:
                closed[col] = pd.to_datetime(closed[col], utc=True)

    eq = pd.Series(
        [s["equity"] for s in portfolio.equity_snapshots],
        index=pd.to_datetime(
            [s["date"] for s in portfolio.equity_snapshots], utc=True, format="mixed"
        ),
    )
    metrics = compute_metrics(closed, eq)
    last_close = float(df.iloc[-1]["close"])
    equity = portfolio.mark_to_market_equity(last_close)
    total_return = (equity / portfolio.initial_cash - 1) * 100 if portfolio.initial_cash else 0.0
    return {
        "closed": closed,
        "eq": eq,
        "metrics": metrics,
        "equity": equity,
        "total_return": total_return,
    }


def export_paper_page(
    output_dir: Path,
    style: str = "swing",
    strategy: str | None = None,
    *,
    refresh: bool = False,
    depth: int = 1,
) -> Path | None:
    """Write ``paper/{style}_{strategy}.html``; return None if portfolio missing."""
    cfg = load_style_config(style)
    strategy = strategy or cfg.get("strategy", "ema_pullback")

    portfolio = PaperPortfolio.load(style, strategy)
    if portfolio is None:
        return None

    df, data_source = _prepare_dataframe(style, cfg, refresh)
    if df.empty:
        return None

    start_ts = pd.Timestamp(portfolio.last_processed_bar or portfolio.started_at)
    if start_ts.tzinfo is None and df.index.tz is not None:
        start_ts = start_ts.tz_localize("UTC")
    paper_df = df[df.index >= start_ts].copy()
    if paper_df.empty:
        paper_df = df.tail(min(120, len(df))).copy()

    summary = _paper_summary(portfolio, df)
    closed = summary["closed"]
    eq = summary["eq"]
    metrics = summary["metrics"]
    equity = summary["equity"]
    total_return = summary["total_return"]

    strat_label = STRATEGY_LABELS.get(strategy, strategy)
    style_label = STYLE_LABELS.get(style, style)
    title = f"Paper — {strat_label} ({style_label})"

    charts = [
        plot_equity_and_drawdown(eq, title="評価額 & ドローダウン"),
        plot_price_and_trades(paper_df, closed, title="価格 & トレード（Paper 期間）"),
        plot_trade_pnl(closed, title="トレード別 PnL %"),
    ]
    chart_html = ""
    for i, fig in enumerate(charts):
        chart_html += fig_to_html_block(
            fig,
            include_plotlyjs="cdn" if i == 0 else False,
            div_id=f"chart-{i}",
        )

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
            pnl = float(row.get("pnl_pct", 0))
            cls = "positive" if pnl > 0 else "negative" if pnl < 0 else ""
            trades_rows += (
                "<tr>"
                f"<td>{escape(str(row.get('side', '')))}</td>"
                f"<td>{escape(str(row.get('entry_time', '')))}</td>"
                f"<td>{escape(str(row.get('exit_time', '')))}</td>"
                f'<td class="{cls}">{pnl:+.2f}%</td>'
                f"<td>{escape(str(row.get('reason', '')))}</td>"
                "</tr>"
            )
    else:
        trades_rows = '<tr><td colspan="5" class="muted">まだクローズドトレードはありません</td></tr>'

    ret_cls = "positive" if total_return >= 0 else "negative"
    body = f"""
    <div class="metrics">
      <div class="metric"><label>評価額</label><value>${equity:,.0f}</value></div>
      <div class="metric {ret_cls}"><label>総リターン</label><value>{total_return:+.2f}%</value></div>
      <div class="metric"><label>Win率</label><value>{metrics.get('win_rate', 0):.1%}</value></div>
      <div class="metric"><label>PF</label><value>{metrics.get('profit_factor', 0):.2f}</value></div>
      <div class="metric"><label>トレード数</label><value>{metrics.get('total_trades', 0)}</value></div>
      <div class="metric"><label>現金</label><value>${portfolio.cash:,.0f}</value></div>
    </div>
    <section><h2>建玉</h2><p>{position_html}</p></section>
    {chart_html}
    <section>
      <h2>クローズドトレード</h2>
      <table>
        <thead><tr><th>Side</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr></thead>
        <tbody>{trades_rows}</tbody>
      </table>
    </section>
    """

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title=title,
        subtitle=f"データ: {data_source}  |  最終足: {df.index[-1]}  |  最終実行: {portfolio.last_run_at or '—'}",
        body=body,
        generated=generated,
        nav_active="paper",
        depth=depth,
    )

    paper_dir = output_dir / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    safe = f"{style}_{strategy}".replace("/", "_")
    path = paper_dir / f"{safe}.html"
    path.write_text(html, encoding="utf-8")
    return path


def export_paper_dashboard(
    output_dir: Path,
    style: str = "swing",
    strategy: str | None = None,
    *,
    refresh: bool = False,
) -> Path:
    """Legacy: export single paper page as index.html."""
    path = export_paper_page(output_dir, style, strategy, refresh=refresh, depth=0)
    if path is None:
        raise RuntimeError(f"Paper 口座がありません: {style}/{strategy}")
    index = output_dir / "index.html"
    index.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    (output_dir / ".nojekyll").touch()
    return index


def paper_summary_row(style: str, strategy: str, *, refresh: bool = False) -> dict | None:
    """Collect KPI row for hub comparison table."""
    portfolio = PaperPortfolio.load(style, strategy)
    if portfolio is None:
        return None
    cfg = load_style_config(style)
    try:
        df, _ = _prepare_dataframe(style, cfg, refresh)
    except Exception:
        return None
    if df.empty:
        return None
    summary = _paper_summary(portfolio, df)
    m = summary["metrics"]
    strat_label = STRATEGY_LABELS.get(strategy, strategy)
    style_label = STYLE_LABELS.get(style, style)
    safe = f"{style}_{strategy}".replace("/", "_")
    return {
        "style": style,
        "strategy": strategy,
        "style_label": style_label,
        "strategy_label": strat_label,
        "equity": summary["equity"],
        "total_return_pct": summary["total_return"],
        "win_rate": m.get("win_rate", 0),
        "profit_factor": m.get("profit_factor", 0),
        "total_trades": m.get("total_trades", 0),
        "max_drawdown_pct": m.get("max_drawdown_pct", 0),
        "last_run": portfolio.last_run_at,
        "href": f"paper/{safe}.html",
        "currency": "USD",
    }


def diversified_paper_summary_row(book) -> dict:
    from signalforge.paper.diversified import DiversifiedPaperBook
    from signalforge.report.dashboard_strategies import STRATEGY_LABELS

    if not isinstance(book, DiversifiedPaperBook):
        raise TypeError("expected DiversifiedPaperBook")
    sim = book.last_sim or {}
    safe = f"diversified_{book.style}_{book.strategy}".replace("/", "_")
    strat_label = STRATEGY_LABELS.get(book.strategy, book.strategy)
    style_label = STYLE_LABELS.get(book.style, book.style)
    accepted = int(sim.get("accepted_trades") or 0)
    skipped = int(sim.get("skipped_overlap") or 0)
    return {
        "style": book.style,
        "strategy": book.strategy,
        "style_label": style_label,
        "strategy_label": f"{strat_label}（1口座·{book.cohort}）",
        "equity": float(sim.get("final_equity") or book.initial_capital),
        "total_return_pct": float(sim.get("total_return_pct") or 0.0),
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "total_trades": accepted,
        "max_drawdown_pct": 0.0,
        "last_run": book.last_run_at,
        "href": f"paper/{safe}.html",
        "currency": "JPY",
        "skipped_trades": skipped,
        "universe_size": book.universe_size,
    }


def export_diversified_paper_page(output_dir: Path, book, *, depth: int = 1, refresh: bool = False) -> Path | None:
    from signalforge.lab.portfolio_sim import unpack_equity_daily
    from signalforge.paper.diversified import DiversifiedPaperBook
    from signalforge.report.benchmark import align_benchmark_to_equity, load_nikkei225_close
    from signalforge.report.charts import plot_equity_vs_benchmark_index

    if not isinstance(book, DiversifiedPaperBook):
        return None
    sim = book.last_sim or {}
    strat_label = STRATEGY_LABELS.get(book.strategy, book.strategy)
    style_label = STYLE_LABELS.get(book.style, book.style)
    safe = f"diversified_{book.style}_{book.strategy}".replace("/", "_")
    ret = float(sim.get("total_return_pct") or 0)
    ret_cls = "positive" if ret >= 0 else "negative"
    chart_html = ""
    eq_raw = unpack_equity_daily(sim.get("equity_daily") or {})
    if not eq_raw.empty:
        nikkei = load_nikkei225_close(refresh=refresh)
        eq_idx, nik_idx = align_benchmark_to_equity(eq_raw, nikkei)
        fig = plot_equity_vs_benchmark_index(eq_idx, nik_idx, title="フォワード期間 · 資産 vs 日経225")
        chart_html = fig_to_html_block(fig, include_plotlyjs="cdn", div_id="equity-nikkei")
    body = f"""
    <div class="info-box">
      1口座 ¥{book.initial_capital:,.0f} · 同時最大 {book.max_positions} 銘柄 ·
      1エントリー {book.position_pct * 100:.0f}% · 先着（枠不足はスキップ）<br>
      ユニバース: {escape(book.cohort)} · {book.universe_size} 銘柄 ·
      エントリ開始: {escape(book.entry_cutoff)} 以降
    </div>
    <div class="metrics">
      <div class="metric"><label>評価額</label><value>¥{float(sim.get('final_equity', book.initial_capital)):,.0f}</value></div>
      <div class="metric"><label>総リターン</label><value class="{ret_cls}">{ret:+.2f}%</value></div>
      <div class="metric"><label>採用トレード</label><value>{int(sim.get('accepted_trades') or 0)}</value></div>
      <div class="metric"><label>スキップ</label><value>{int(sim.get('skipped_overlap') or 0)}</value></div>
    </div>
    {chart_html}
    <p class="muted">指数はエントリ開始日=100。日経は 1321.T（日経225連動ETF）の終値。GitHub Actions 日次更新後のスナップショット。</p>
    """
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title=f"Paper 分散 · {strat_label}",
        subtitle=f"{style_label} / {book.strategy}",
        body=body,
        generated=generated,
        nav_active="paper",
        depth=depth,
    )
    paper_dir = output_dir / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    path = paper_dir / f"{safe}.html"
    path.write_text(html, encoding="utf-8")
    return path
