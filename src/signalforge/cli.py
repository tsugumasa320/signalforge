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
@click.option("--port", default=8501, show_default=True)
@click.option("--no-browser", is_flag=True, help="Do not auto-open browser")
def dashboard(port: int, no_browser: bool) -> None:
    """Launch Streamlit interactive analysis dashboard."""
    import os
    import subprocess
    import sys

    from signalforge.bootstrap import warmup_native_libs

    warmup_native_libs()

    path = Path(__file__).resolve().parent / "report" / "dashboard.py"
    root = Path(__file__).resolve().parents[2]
    url = f"http://localhost:{port}"

    click.echo("")
    click.echo("=" * 50)
    click.echo("  SignalForge GUI")
    click.echo("=" * 50)
    click.echo(f"  URL: {url}")
    click.echo("")
    click.echo("  ※ このターミナルは閉じないでください（閉じると停止します）")
    click.echo("  ※ ブラウザが自動で開かない場合は上記 URL を直接開いてください")
    click.echo("")
    click.echo("  停止: Ctrl+C")
    click.echo("=" * 50)
    click.echo("")

    args = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(path),
        "--server.port",
        str(port),
        "--server.address",
        "localhost",
    ]
    if no_browser:
        args.append("--server.headless")
        args.append("true")

    env = os.environ.copy()
    env.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")
    subprocess.run(args, cwd=str(root), check=False, env=env)


if __name__ == "__main__":
    main()
