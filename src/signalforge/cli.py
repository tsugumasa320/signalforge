from __future__ import annotations

import json
from pathlib import Path

import click

from signalforge.config import data_dir, load_style_config
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.interpret.journal import TradeJournal
from signalforge.optimize.bayesian import bayesian_optimize
from signalforge.optimize.objective import make_objective
from signalforge.optimize.spaces import build_cfg_override, strategies_for_style, suggest_params
from signalforge.pipeline import run_backtest_pipeline
from signalforge.report.trade_report import save_report


def _print_metrics(label: str, m: dict) -> None:
    click.echo(f"\n--- {label} ---")
    click.echo(f"Trades: {m.get('total_trades', 0)}")
    click.echo(f"Win rate: {m.get('win_rate', 0):.1%}")
    click.echo(f"Profit factor (net): {m.get('profit_factor', 0):.2f}")
    if m.get("gross_profit_factor") is not None:
        click.echo(f"Profit factor (gross): {m.get('gross_profit_factor', 0):.2f}")
    click.echo(f"Sharpe: {m.get('sharpe', 0):.2f}")
    click.echo(f"Max DD: {m.get('max_drawdown_pct', 0):.2f}%")
    click.echo(f"Total return: {m.get('total_return_pct', 0):.2f}%")
    click.echo(f"Avg PnL: {m.get('avg_pnl_pct', 0):.2f}%")
    if m.get("total_cost_usd"):
        click.echo(
            f"Costs: fees ${m.get('total_fees_usd', 0):,.2f} + "
            f"slippage ${m.get('total_slippage_usd', 0):,.2f} = "
            f"${m.get('total_cost_usd', 0):,.2f} "
            f"(${m.get('avg_cost_per_trade_usd', 0):,.2f}/trade)"
        )


@click.group()
def main() -> None:
    """SignalForge — NVDA multi-horizon technical analysis."""


@main.command()
@click.option("--ticker", default="NVDA")
@click.option("--timeframe", default="1d", type=click.Choice(["1d", "1h", "5m", "15m"]))
@click.option("--source", default="auto", type=click.Choice(["auto", "yfinance", "alpaca"]))
@click.option("--refresh", is_flag=True)
@click.option("--with-correlations", is_flag=True, help="Also fetch QQQ/SOXX for the style timeframe")
def fetch(ticker: str, timeframe: str, source: str, refresh: bool, with_correlations: bool) -> None:
    """Fetch and cache market data."""
    import os

    if source == "auto":
        source = "alpaca" if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY") else "yfinance"
    fetcher = MarketDataFetcher(data_source=source)
    cache = ParquetCache()
    df = cache.load_or_fetch(ticker, timeframe, fetcher, refresh=True if refresh else False)
    click.echo(f"Cached {ticker} {timeframe} ({source}): {len(df)} bars → {cache.path(ticker, timeframe)}")
    if with_correlations:
        for sym in ("QQQ", "SOXX"):
            cdf = cache.load_or_fetch(sym, timeframe, fetcher, refresh=True if refresh else False)
            click.echo(f"Cached {sym} {timeframe}: {len(cdf)} bars → {cache.path(sym, timeframe)}")


@main.command()
@click.option("--style", default="swing", type=click.Choice(["swing", "swing_high_winrate", "daytrade"]))
@click.option("--strategy", default=None)
@click.option("--refresh", is_flag=True)
@click.option("--ml-filter", is_flag=True)
@click.option(
    "--cost-model",
    default="alpaca",
    type=click.Choice(["legacy", "alpaca", "alpaca_conservative"]),
    help="Trading cost model (default: Alpaca regulatory + slippage)",
)
def backtest(style: str, strategy: str | None, refresh: bool, ml_filter: bool, cost_model: str) -> None:
    """Run backtest with trade journal."""
    result = run_backtest_pipeline(style, strategy, refresh, ml_filter, cost_model=cost_model)
    click.echo(f"\n=== Backtest: {result['style']} / {result['strategy']} ===")
    click.echo(f"Data source: {result.get('data_source', 'unknown')}")
    click.echo(f"Cost model: {result.get('cost_model', cost_model)}")
    click.echo(f"Run ID: {result['run_id']}")
    if result.get("backtest_window"):
        click.echo(f"評価期間: {result['backtest_window']}")
    _print_metrics("全期間", result["metrics"])

    ml_trained = result.get("ml_report", {}).get("trained")
    if ml_trained:
        mr = result["ml_report"]
        click.echo(f"\n--- ML Walk-Forward ---")
        click.echo(f"Folds: {mr.get('folds', 0)}")
        avg = mr.get("avg_oos_accuracy")
        if avg is not None:
            click.echo(f"Avg OOS label accuracy: {avg:.1%}")
        _print_metrics("OOS 期間のみ", result.get("metrics_oos", {}))
        from signalforge.report.dashboard_components import oos_metrics_from_trades

        oos_detail = oos_metrics_from_trades(result["trades"], result["equity"])
        click.echo(f"OOS Win rate (trade-level): {oos_detail.get('win_rate', 0):.1%}")
        _print_metrics("OOS 外（TA のみ）", result.get("metrics_in_sample", {}))

    run_id = result["run_id"]
    journal_path = data_dir() / "reports" / f"journal_{run_id}.json"
    click.echo(f"\nJournal: {journal_path}")


@main.command()
@click.option("--trade-id", type=int, required=True)
@click.option("--run-id", default=None)
def explain(trade_id: int, run_id: str | None) -> None:
    """Explain a single trade from journal."""
    reports = data_dir() / "reports"
    if run_id is None:
        journals = sorted(reports.glob("journal_*.json"))
        if not journals:
            click.echo("No journals found. Run backtest first.")
            return
        run_id = journals[-1].stem.replace("journal_", "")

    journal = TradeJournal.load(reports, run_id)
    trade = journal.get_trade(trade_id)
    if not trade:
        click.echo(f"Trade {trade_id} not found in run {run_id}")
        return
    click.echo(json.dumps(trade.to_dict(), ensure_ascii=False, indent=2))


@main.command()
@click.option("--date", required=True, help="YYYY-MM-DD")
@click.option("--run-id", default=None)
def audit(date: str, run_id: str | None) -> None:
    """Show signal audits for a date."""
    reports = data_dir() / "reports"
    if run_id is None:
        journals = sorted(reports.glob("journal_*.json"))
        if not journals:
            click.echo("No journals found.")
            return
        run_id = journals[-1].stem.replace("journal_", "")

    journal = TradeJournal.load(reports, run_id)
    for t in journal.trades:
        if date in t.timestamp:
            click.echo(f"Trade #{t.trade_id}: {t.summary_ja}")
            click.echo(f"  Passed: {t.rules_audit.get('passed', [])}")
            click.echo(f"  Failed: {t.rules_audit.get('failed', [])}")
    for r in journal.rejected:
        if date in r.timestamp:
            click.echo(f"Rejected: {r.summary_ja}")


@main.command()
@click.option("--run-id", default=None)
@click.option("--format", "fmt", default="md", type=click.Choice(["md", "json"]))
def report(run_id: str | None, fmt: str) -> None:
    """Generate trade journal report."""
    reports = data_dir() / "reports"
    if run_id is None:
        journals = sorted(reports.glob("journal_*.json"))
        if not journals:
            click.echo("No journals found.")
            return
        run_id = journals[-1].stem.replace("journal_", "")

    journal = TradeJournal.load(reports, run_id)
    out = save_report(journal, reports, fmt)
    click.echo(f"Report saved: {out}")


@main.command()
@click.option("--style", default="swing")
@click.option("--strategies", default="ema_pullback,macd_cross")
@click.option("--ml-filter", is_flag=True, help="Compare with walk-forward ML filter (OOS metrics)")
def compare(style: str, strategies: str, ml_filter: bool) -> None:
    """Compare multiple strategies."""
    names = [s.strip() for s in strategies.split(",")]
    click.echo(f"\n=== Compare ({style}) — TA only ===")
    for name in names:
        result = run_backtest_pipeline(style, name)
        m = result["metrics"]
        click.echo(f"{name:20s} PF={m['profit_factor']:.2f}  Sharpe={m['sharpe']:.2f}  Trades={m['total_trades']}")

    if ml_filter:
        click.echo(f"\n=== Compare ({style}) — TA + ML (OOS) ===")
        for name in names:
            result = run_backtest_pipeline(style, name, ml_filter=True)
            m = result.get("metrics_oos", {})
            click.echo(
                f"{name:20s} OOS PF={m.get('profit_factor', 0):.2f}  "
                f"Trades={m.get('total_trades', 0)}  "
                f"Win={m.get('win_rate', 0):.1%}"
            )


@main.command()
@click.option("--style", default="swing")
@click.option("--strategy", default="ema_pullback")
@click.option("--trials", default=30)
@click.option(
    "--metric",
    default="oos_pf",
    type=click.Choice(["pf", "oos_pf", "sharpe", "oos_sharpe", "win_rate", "oos_win_rate"]),
    help="Optimization target (oos_* uses walk-forward ML when --ml-filter)",
)
@click.option("--ml-filter", is_flag=True, help="Enable walk-forward ML; default metric is OOS PF")
@click.option("--min-trades", default=5, show_default=True)
@click.option("--min-pf", default=1.0, show_default=True, help="Minimum PF when optimizing win rate")
def optimize(style: str, strategy: str, trials: int, metric: str, ml_filter: bool, min_trades: int, min_pf: float) -> None:
    """Bayesian optimization over interpretable parameters."""
    if ml_filter and metric == "pf":
        metric = "oos_pf"
    if metric in ("win_rate", "oos_win_rate") and not ml_filter:
        ml_filter = True

    objective = make_objective(
        style,
        strategy,
        metric=metric,
        ml_filter=ml_filter,
        min_trades=min_trades,
        min_profit_factor=min_pf,
    )
    best = bayesian_optimize(objective, n_trials=trials)
    params = best["best_params"]
    base_cfg = load_style_config(style)
    cfg_override = build_cfg_override(strategy, params, base_cfg)

    click.echo(f"\n=== Optimize: {style} / {strategy} (metric={metric}, ml={ml_filter}) ===")
    click.echo(f"Best params: {params}")
    click.echo(f"Best score: {best['best_value']:.3f}")

    result = run_backtest_pipeline(style, strategy, ml_filter=ml_filter, cfg_override=cfg_override)
    _print_metrics("最適パラメータ — 全期間", result["metrics"])
    if ml_filter or metric.startswith("oos"):
        _print_metrics("最適パラメータ — OOS", result.get("metrics_oos", {}))
        from signalforge.report.dashboard_components import oos_metrics_from_trades

        oos_m = oos_metrics_from_trades(result["trades"], result["equity"])
        click.echo(f"OOS Win rate: {oos_m.get('win_rate', 0):.1%}")
        mr = result.get("ml_report", {})
        if mr.get("trained"):
            avg = mr.get("avg_oos_accuracy")
            if avg is not None:
                click.echo(f"Avg OOS label accuracy: {avg:.1%}")


@main.command()
@click.option("--style", default="swing", type=click.Choice(["swing", "daytrade"]))
@click.option("--ml-filter", is_flag=True, help="Rank strategies by OOS metrics with ML filter")
@click.option("--optimize-trials", default=20, help="Optuna trials for the top TA strategy (0=skip)")
@click.option("--top-strategy", default=None, help="Force optimization target strategy")
def explore(style: str, ml_filter: bool, optimize_trials: int, top_strategy: str | None) -> None:
    """Compare all strategies, optionally optimize the best candidate."""
    names = list(strategies_for_style(style))
    click.echo(f"\n=== Explore ({style}) — TA only ===")
    ta_rows: list[tuple[str, dict]] = []
    for name in names:
        result = run_backtest_pipeline(style, name)
        m = result["metrics"]
        ta_rows.append((name, m))
        click.echo(
            f"{name:16s} PF={m['profit_factor']:.2f}  Sharpe={m['sharpe']:.2f}  "
            f"Trades={m['total_trades']}  DD={m['max_drawdown_pct']:.1f}%"
        )

    oos_rows: list[tuple[str, dict]] = []
    if ml_filter:
        click.echo(f"\n=== Explore ({style}) — TA + ML (OOS) ===")
        for name in names:
            result = run_backtest_pipeline(style, name, ml_filter=True)
            m = result.get("metrics_oos", {})
            oos_rows.append((name, m))
            click.echo(
                f"{name:16s} OOS PF={m.get('profit_factor', 0):.2f}  "
                f"Trades={m.get('total_trades', 0)}  Win={m.get('win_rate', 0):.1%}"
            )

    rank_source = oos_rows if ml_filter and oos_rows else ta_rows
    best_name = top_strategy or max(rank_source, key=lambda x: x[1].get("profit_factor", 0))[0]
    best_pf = next(m for n, m in rank_source if n == best_name).get("profit_factor", 0)
    click.echo(f"\nTop strategy: {best_name} (PF={best_pf:.2f})")

    if optimize_trials > 0:
        click.echo(f"\n=== Quick optimize: {best_name} ({optimize_trials} trials) ===")
        metric = "oos_pf" if ml_filter else "pf"
        objective = make_objective(style, best_name, metric=metric, ml_filter=ml_filter)
        best = bayesian_optimize(objective, n_trials=optimize_trials)
        click.echo(f"Best params: {best['best_params']}")
        click.echo(f"Best {metric}: {best['best_value']:.3f}")


@main.command("verify-profit")
@click.option("--style", default="swing", type=click.Choice(["swing", "daytrade"]))
@click.option("--strategy", default=None, help="Single strategy (default: all for style)")
@click.option("--ml-filter", is_flag=True, help="Include walk-forward ML filter")
def verify_profit(style: str, strategy: str | None, ml_filter: bool) -> None:
    """Compare profitability under legacy vs Alpaca fee schedules."""
    from signalforge.backtest.metrics import compute_metrics
    from signalforge.config import load_style_config
    from signalforge.optimize.spaces import build_cfg_override, strategies_for_style

    names = [strategy] if strategy else list(strategies_for_style(style))
    presets = ("legacy", "alpaca", "alpaca_conservative")
    optimized_macd = {
        "adx_threshold": 23,
        "ema_trend": 200,
        "long_only": True,
    }

    click.echo("\n=== Profit verification (NVDA) ===")
    click.echo("Broker model: Alpaca API (commission-free equities + SEC/TAF/CAT pass-through)")
    click.echo("Sources: BrokFeeSched Jul 2026, docs.alpaca.markets/us/docs/regulatory-fees")
    if style == "swing":
        click.echo("Note: Alpaca cash accounts are long-only; short signals require margin.")
    click.echo("")

    for name in names:
        click.echo(f"--- {name} {'+ ML' if ml_filter else '(TA only)'} ---")
        rows = []
        base_cfg = load_style_config(style)
        cfg_override = None
        if name == "macd_cross":
            cfg_override = build_cfg_override("macd_cross", optimized_macd, base_cfg)
            click.echo("  (optimized: ADX>23, EMA200, long_only)")

        for preset in presets:
            result = run_backtest_pipeline(
                style,
                name,
                ml_filter=ml_filter,
                cost_model=preset,
                cfg_override=cfg_override,
            )
            if ml_filter and not result["trades"].empty and "is_oos" in result["trades"].columns:
                oos_trades = result["trades"][result["trades"]["is_oos"]]
                m = compute_metrics(oos_trades, result["equity"])
            else:
                m = result["metrics"]
            label = preset
            pf = m.get("profit_factor", 0)
            ret = m.get("total_return_pct", 0)
            cost = m.get("total_cost_usd", 0)
            rows.append((label, pf, ret, m.get("total_trades", 0), cost))
            click.echo(
                f"  {label:22s} PF={pf:5.2f}  Return={ret:7.1f}%  "
                f"Trades={m.get('total_trades', 0):3d}  Costs=${cost:,.0f}"
            )

        alpaca = next(r for r in rows if r[0] == "alpaca")
        if alpaca[1] >= 1.05 and alpaca[2] > 0:
            verdict = "✓ Alpaca costs下でも利益余地あり"
        elif alpaca[1] >= 1.0:
            verdict = "△ ギリギリ（コストで優位性ほぼ消失）"
        else:
            verdict = "✗ Alpaca 実コスト込みでは期待値マイナス"
        click.echo(f"  → {verdict}\n")


@main.command()
def doctor() -> None:
    """Check local setup for dashboard / CLI."""
    import socket
    import sys

    root = Path(__file__).resolve().parents[2]
    click.echo(f"Project: {root}")
    click.echo(f"Python:  {sys.executable} ({sys.version.split()[0]})")

    dash = root / "src" / "signalforge" / "report" / "dashboard.py"
    click.echo(f"Dashboard file: {'OK' if dash.is_file() else 'MISSING'}")

    venv = root / ".venv"
    click.echo(f".venv: {'OK' if venv.is_dir() else 'MISSING — run: uv sync --extra dev'}")

    try:
        import streamlit

        static = Path(streamlit.__file__).parent / "static" / "index.html"
        click.echo(f"Streamlit static: {'OK' if static.is_file() else 'BROKEN — recreate .venv'}")
    except ImportError:
        click.echo("Streamlit: NOT INSTALLED — run: uv sync")

    port = 8501
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        in_use = sock.connect_ex(("127.0.0.1", port)) == 0
    click.echo(f"Port {port}: {'IN USE (dashboard may already be running)' if in_use else 'free'}")

    data = root / "data" / "NVDA_1d.pkl"
    click.echo(f"Data cache: {'OK' if data.is_file() else 'MISSING — run: uv run signalforge fetch --ticker NVDA --timeframe 1d'}")

    click.echo("\nLaunch (background, survives terminal close):")
    click.echo("  uv run signalforge dashboard start")
    click.echo("Stop: uv run signalforge dashboard stop")
    click.echo("Status: uv run signalforge dashboard status")


@main.group(invoke_without_command=True)
@click.option("--port", default=8501, show_default=True, help="Preferred TCP port")
@click.pass_context
def dashboard(ctx: click.Context, port: int) -> None:
    """Launch / manage Streamlit dashboard."""
    ctx.ensure_object(dict)
    ctx.obj["port"] = port
    if ctx.invoked_subcommand is None:
        ctx.invoke(dashboard_start, port=port, browser=True, force=False)


@dashboard.command("start")
@click.option("--port", default=8501, show_default=True)
@click.option("--browser/--no-browser", "open_browser", default=True, help="Open browser after start")
@click.option("--force", is_flag=True, help="Restart if already running")
def dashboard_start(port: int, open_browser: bool, force: bool) -> None:
    """Start dashboard in background (keeps running after terminal closes)."""
    from signalforge.report.dashboard_daemon import start

    try:
        info = start(port, open_browser=open_browser, force=force)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    if info.get("already_running"):
        click.echo(f"✅ すでに起動中: {info['url']}  (PID {info.get('pid', '?')})")
    else:
        click.echo(f"✅ バックグラウンド起動: {info['url']}")
        click.echo(f"   PID: {info['pid']}  |  ログ: {info['log']}")
    click.echo("   停止: uv run signalforge dashboard stop")


@dashboard.command("stop")
def dashboard_stop() -> None:
    """Stop background dashboard."""
    from signalforge.report.dashboard_daemon import stop

    if stop():
        click.echo("ダッシュボードを停止しました。")
    else:
        click.echo("停止対象のダッシュボードは見つかりませんでした。")


@dashboard.command("status")
def dashboard_status() -> None:
    """Show dashboard process status."""
    from signalforge.report.dashboard_daemon import status

    info = status()
    if info["running"]:
        click.echo(f"✅ 起動中: {info['url']}  (PID {info.get('pid') or 'unknown'})")
    else:
        click.echo("停止中")
    click.echo(f"ログ: {info['log']}")


@dashboard.command("run")
@click.option("--port", default=8501, show_default=True)
@click.option("--no-browser", is_flag=True, help="Do not auto-open browser")
def dashboard_run(port: int, no_browser: bool) -> None:
    """Run dashboard in foreground (stops when terminal closes)."""
    from signalforge.report.dashboard_daemon import run_foreground

    click.echo("⚠ フォアグラウンドモード: ターミナルを閉じると停止します。")
    run_foreground(port, no_browser=no_browser)


@dashboard.command("export")
@click.option("--output", default="_site", type=click.Path(), show_default=True, help="Output directory")
@click.option("--style", default=None, help="Export single strategy only (legacy)")
@click.option("--strategy", default=None)
@click.option("--refresh/--no-refresh", default=False, help="Re-fetch market data before export")
def dashboard_export(output: str, style: str | None, strategy: str | None, refresh: bool) -> None:
    """Export static HTML site (hub + all strategies) for GitHub Pages."""
    out = Path(output)
    if style:
        from signalforge.report.static_dashboard import export_paper_dashboard

        cfg = load_style_config(style)
        strategy = strategy or cfg.get("strategy", "ema_pullback")
        try:
            path = export_paper_dashboard(out, style, strategy, refresh=refresh)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"✅ 静的ダッシュボード: {path.resolve()}")
        return

    from signalforge.report.static_site import export_full_site

    path = export_full_site(out, refresh=refresh)
    click.echo(f"✅ 統合ダッシュボード: {path.resolve()}")
    click.echo(f"   Paper: {len(list((out / 'paper').glob('*.html')))} ページ")
    click.echo(f"   戦略解説: {len(list((out / 'guide').glob('*.html')))} ページ")


@main.group()
def paper() -> None:
    """Forward paper trading — daily data refresh + virtual PnL tracking."""


@paper.command("init")
@click.option("--style", default="swing", type=click.Choice(["swing", "swing_high_winrate", "daytrade"]))
@click.option("--strategy", default=None)
@click.option("--cost-model", default="alpaca", type=click.Choice(["legacy", "alpaca", "alpaca_conservative"]))
def paper_init(style: str, strategy: str | None, cost_model: str) -> None:
    """Start a new paper account from the latest bar (forward-only)."""
    from signalforge.paper.portfolio import PaperPortfolio
    from signalforge.paper.runner import init_paper_portfolio

    cfg = load_style_config(style)
    strategy = strategy or cfg.get("strategy", "ema_pullback")
    existing = PaperPortfolio.load(style, strategy)
    if existing:
        raise click.ClickException(
            f"既に paper 口座があります。リセットする場合: signalforge paper reset --style {style} --strategy {strategy}"
        )
    p = init_paper_portfolio(style, strategy, cost_model=cost_model, refresh=True)
    click.echo(f"✅ Paper 口座を作成しました: {style} / {strategy}")
    click.echo(f"   開始時点の最終足: {p.last_processed_bar}")
    click.echo(f"   初期資金: ${p.initial_cash:,.0f}")
    click.echo(f"   保存先: {p.save()}")
    click.echo(f"\n毎日実行: uv run signalforge paper run --style {style} --strategy {strategy}")


@paper.command("run-all")
@click.option("--refresh/--no-refresh", default=True, help="Fetch latest market data")
@click.option("--cost-model", default=None, type=click.Choice(["legacy", "alpaca", "alpaca_conservative"]))
def paper_run_all(refresh: bool, cost_model: str | None) -> None:
    """Fetch data and advance all configured paper accounts."""
    from signalforge.paper.matrix import PAPER_SIMULATIONS, run_all_paper_daily

    results = run_all_paper_daily(refresh=refresh, cost_model=cost_model)
    click.echo(f"\n=== Paper run-all ({len(PAPER_SIMULATIONS)} 口座) ===")
    for r in results:
        label = f"{r['style']}/{r['strategy']}"
        if not r.get("ok"):
            click.echo(f"  ✗ {label}: {r.get('error', 'failed')}")
            continue
        eq = r.get("equity", 0)
        status = r.get("status", "?")
        click.echo(f"  ✓ {label}: ${eq:,.0f} ({status})")


@paper.command("run")
@click.option("--style", default="swing", type=click.Choice(["swing", "swing_high_winrate", "daytrade"]))
@click.option("--strategy", default=None)
@click.option("--refresh/--no-refresh", default=True, help="Fetch latest market data")
@click.option("--cost-model", default=None, type=click.Choice(["legacy", "alpaca", "alpaca_conservative"]))
def paper_run(style: str, strategy: str | None, refresh: bool, cost_model: str | None) -> None:
    """Fetch latest data and process new bars (run daily via cron)."""
    from signalforge.paper.runner import run_paper_daily

    cfg = load_style_config(style)
    strategy = strategy or cfg.get("strategy", "ema_pullback")
    try:
        out = run_paper_daily(style, strategy, cost_model=cost_model, refresh=refresh)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    p = out["portfolio"]
    click.echo(f"\n=== Paper: {style} / {strategy} ===")
    click.echo(f"Data: {out.get('data_source', '?')}  |  最終足: {out.get('last_bar', '?')}")

    if out["status"] == "up_to_date":
        click.echo(f"\n{out['message']}")
        click.echo(f"現在評価額: ${out['equity']:,.0f}")
        return

    click.echo(f"処理した新規足: {out['new_bars']} 本")
    if out.get("new_trades"):
        click.echo(f"新規トレード: {len(out['new_trades'])} 件")
        for t in out["new_trades"]:
            click.echo(
                f"  - {t.get('side')} {t.get('entry_time')} → {t.get('exit_time')} "
                f"PnL {float(t.get('pnl_pct', 0)):+.2f}% ({t.get('reason', '')})"
            )
    else:
        click.echo("新規トレード: なし")

    pos = out.get("position")
    if pos:
        click.echo(f"\n建玉: {pos.get('side')} @ {pos.get('entry_price', 0):.2f} ({pos.get('entry_time', '')})")
    else:
        click.echo("\n建玉: なし")

    click.echo(f"\n--- 累積成績（paper 開始以降） ---")
    click.echo(f"評価額: ${out['equity']:,.0f}")
    click.echo(f"総リターン: {out.get('total_return_pct', 0):.2f}%")
    m = out.get("metrics", {})
    click.echo(f"クローズドトレード: {m.get('total_trades', 0)}")
    click.echo(f"Win率: {m.get('win_rate', 0):.1%}")
    click.echo(f"PF: {m.get('profit_factor', 0):.2f}")
    click.echo(f"\n状態ファイル: {p.save()}")


@paper.command("status")
@click.option("--style", default="swing", type=click.Choice(["swing", "swing_high_winrate", "daytrade"]))
@click.option("--strategy", default=None)
def paper_status(style: str, strategy: str | None) -> None:
    """Show paper account status."""
    from signalforge.paper.portfolio import PaperPortfolio

    cfg = load_style_config(style)
    strategy = strategy or cfg.get("strategy", "ema_pullback")
    p = PaperPortfolio.load(style, strategy)
    if not p:
        raise click.ClickException("Paper 口座がありません。`signalforge paper init` を実行してください。")

    eq = p.equity_snapshots[-1]["equity"] if p.equity_snapshots else p.cash
    click.echo(f"Paper: {style} / {strategy}")
    click.echo(f"開始: {p.started_at}")
    click.echo(f"最終処理足: {p.last_processed_bar}")
    click.echo(f"最終実行: {p.last_run_at}")
    click.echo(f"現金: ${p.cash:,.0f}")
    click.echo(f"最新評価額: ${eq:,.0f}")
    click.echo(f"クローズドトレード: {len(p.closed_trades)}")
    if p.position:
        click.echo(f"建玉: {p.position.get('side')} @ {p.position.get('entry_price')} ({p.position.get('entry_time')})")


@paper.command("reset")
@click.option("--style", default="swing", type=click.Choice(["swing", "swing_high_winrate", "daytrade"]))
@click.option("--strategy", default=None)
@click.confirmation_option(prompt="Paper 口座をリセットしますか？")
def paper_reset(style: str, strategy: str | None) -> None:
    """Delete paper state and start fresh on next init/run."""
    from signalforge.paper.portfolio import PaperPortfolio, portfolio_path

    cfg = load_style_config(style)
    strategy = strategy or cfg.get("strategy", "ema_pullback")
    path = portfolio_path(style, strategy)
    if path.exists():
        path.unlink()
    click.echo("Paper 口座をリセットしました。`paper init` または `paper run` で再開できます。")


if __name__ == "__main__":
    main()
