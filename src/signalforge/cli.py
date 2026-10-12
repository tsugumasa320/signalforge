from __future__ import annotations

import json
from pathlib import Path

import click

from signalforge.config import (
    data_dir,
    load_implementation_map,
    load_market_config,
    load_media_sources,
    load_style_config,
    load_universe,
    load_web_catalog,
)
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.interpret.journal import TradeJournal
from signalforge.optimize.bayesian import bayesian_optimize
from signalforge.optimize.objective import make_objective
from signalforge.optimize.champion import CHAMPION_MACD_PARAMS, CHAMPION_STRATEGY, CHAMPION_STYLE, champion_cfg_override
from signalforge.optimize.spaces import build_cfg_override, strategies_for_style, suggest_params
from signalforge.pipeline import run_backtest_pipeline
from signalforge.report.trade_report import save_report


STYLE_CHOICES = ["swing", "swing_champion", "swing_high_winrate", "daytrade"]
COST_MODEL_CHOICE = click.Choice(["legacy", "alpaca", "alpaca_conservative", "japan"])


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
    """SignalForge — 日本株マルチホライズン・テクニカル分析。"""


@main.command()
@click.option("--ticker", default=None, help="Single ticker (default: 7203.T)")
@click.option("--universe", default=None, help="Universe yaml name (e.g. japan_liquid)")
@click.option("--timeframe", default="1d", type=click.Choice(["1d", "1h", "5m", "15m"]))
@click.option("--source", default="auto", type=click.Choice(["auto", "yfinance", "alpaca"]))
@click.option("--refresh", is_flag=True)
@click.option("--with-correlations", is_flag=True, help="Also fetch 1321.T / 1570.T")
def fetch(
    ticker: str | None,
    universe: str | None,
    timeframe: str,
    source: str,
    refresh: bool,
    with_correlations: bool,
) -> None:
    """Fetch and cache market data (Japan: yfinance *.T)."""
    import os

    if universe:
        tickers = list(load_universe(universe).get("tickers", []))
    else:
        default = load_market_config("japan").get("default_ticker", "7203.T")
        tickers = [ticker or default]

    if source == "auto":
        source = "yfinance"
        if tickers and not str(tickers[0]).endswith(".T"):
            if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"):
                source = "alpaca"
    fetcher = MarketDataFetcher(data_source=source)
    cache = ParquetCache()
    for sym in tickers:
        df = cache.load_or_fetch(sym, timeframe, fetcher, refresh=True if refresh else False)
        click.echo(f"Cached {sym} {timeframe} ({source}): {len(df)} bars → {cache.path(sym, timeframe)}")
    if with_correlations:
        for sym in load_market_config("japan").get("correlation_tickers", []):
            cdf = cache.load_or_fetch(sym, timeframe, fetcher, refresh=True if refresh else False)
            click.echo(f"Cached {sym} {timeframe}: {len(cdf)} bars → {cache.path(sym, timeframe)}")


@main.command()
@click.option("--refresh", is_flag=True, help="Re-fetch market data")
@click.option("--cost-model", default="japan", type=COST_MODEL_CHOICE)
def champion(refresh: bool, cost_model: str) -> None:
    """Run the champion algorithm: optimized MACD + walk-forward ML (Japan swing)."""
    mc = load_market_config("japan")
    click.echo("\n=== SignalForge Champion ===")
    click.echo(f"{mc.get('default_ticker', '7203.T')} 日足 · MACD + ADX>23 + EMA200 · ML フィルタ（OOS）")
    click.echo("※ 過去データの成績であり、将来の利益を保証しません。\n")

    ta = run_backtest_pipeline(
        CHAMPION_STYLE,
        CHAMPION_STRATEGY,
        refresh,
        ml_filter=False,
        cost_model=cost_model,
        cfg_override={"ml_filter": {"enabled": False}},
    )
    click.echo(f"評価期間: {ta.get('backtest_window', '?')}")
    _print_metrics("Champion TA（全期間）", ta["metrics"])

    ml = run_backtest_pipeline(
        CHAMPION_STYLE,
        CHAMPION_STRATEGY,
        refresh,
        ml_filter=True,
        cost_model=cost_model,
    )
    _print_metrics("Champion TA+ML（OOS）", ml.get("metrics_oos", {}))
    mr = ml.get("ml_report", {})
    if mr.get("trained"):
        click.echo(f"ML folds: {mr.get('folds', 0)}  |  avg OOS accuracy: {mr.get('avg_oos_accuracy', 0):.1%}")
    else:
        click.echo(f"ML: 未学習 ({mr.get('reason', '?')})")

    click.echo("\n使い方: uv run signalforge backtest --style swing_champion --ml-filter")
    click.echo("Paper:  uv run signalforge paper run --style swing_champion --strategy macd_cross")


@main.command()
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
@click.option("--strategy", default="macd_cross")
@click.option("--universe", default="japan_liquid", show_default=True)
@click.option("--cost-model", default="japan", type=COST_MODEL_CHOICE)
@click.option("--refresh", is_flag=True, help="Re-fetch OHLCV for each ticker")
@click.option("--limit", default=0, show_default=True, help="Max tickers (0 = all)")
def scan(
    style: str,
    strategy: str,
    universe: str,
    cost_model: str,
    refresh: bool,
    limit: int,
) -> None:
    """Backtest one strategy across a Japan stock universe."""
    tickers = list(load_universe(universe).get("tickers", []))
    if limit > 0:
        tickers = tickers[:limit]
    click.echo(f"\n=== Scan: {style} / {strategy} · {len(tickers)} 銘柄 ({universe}) ===\n")
    rows: list[tuple[str, float, float, int]] = []
    for sym in tickers:
        try:
            result = run_backtest_pipeline(
                style,
                strategy,
                refresh,
                cost_model=cost_model,
                cfg_override={"ticker": sym},
            )
            m = result["metrics"]
            rows.append((sym, m.get("profit_factor", 0), m.get("win_rate", 0), m.get("total_trades", 0)))
            click.echo(
                f"{sym:10s} PF={m.get('profit_factor', 0):.2f}  "
                f"Win={m.get('win_rate', 0):.1%}  Trades={m.get('total_trades', 0)}"
            )
        except Exception as exc:
            click.echo(f"{sym:10s} ERROR: {exc}")
    if rows:
        rows.sort(key=lambda r: r[1], reverse=True)
        click.echo("\n--- Top PF ---")
        for sym, pf, wr, n in rows[:5]:
            click.echo(f"  {sym}  PF={pf:.2f}  Win={wr:.1%}  Trades={n}")


def _parse_strategy_ids(spec: str, style_filter: str | None, limit: int) -> list[str]:
    from signalforge.config import load_implementation_map

    if spec.startswith("catalog:"):
        want_style = spec.split(":", 1)[1].strip() or None
        if want_style == "all":
            want_style = None
            ids = list(load_implementation_map().get("strategies", {}).keys())
        else:
            ids = []
            cat = load_web_catalog()
            for s in cat.get("strategies", []):
                if not s.get("implemented"):
                    continue
                if want_style and s.get("style") != want_style:
                    continue
                if s["id"] in load_implementation_map().get("strategies", {}):
                    ids.append(s["id"])
        if limit > 0:
            ids = ids[:limit]
        return ids
    ids = [x.strip() for x in spec.split(",") if x.strip()]
    if limit > 0:
        ids = ids[:limit]
    return ids


@main.group()
def hub() -> None:
    """Run all verifications and build ranking/chart hub."""


@hub.command("build")
@click.option("--fetch-data", is_flag=True, default=True, help="Fetch OHLCV for cohort tickers first")
@click.option("--ticker-limit", default=0, type=int, help="Cap tickers per cohort (0=all meta)")
@click.option("--skip-catalog", is_flag=True, help="Skip catalog backtest-all (reuse catalog_backtests.json)")
@click.option("--skip-cohort", is_flag=True, help="Skip strategy×cohort matrix (faster)")
@click.option("--skip-lab", is_flag=True, help="Skip lab matrix")
def hub_build(
    fetch_data: bool,
    ticker_limit: int,
    skip_catalog: bool,
    skip_cohort: bool,
    skip_lab: bool,
) -> None:
    """Execute catalog + cohort + lab backtests, then generate data/reports/hub/index.html."""
    from datetime import datetime, timezone

    from signalforge.compare.runner import preset_specs, run_comparison_matrix
    from signalforge.lab.palette import resolve_rule_ids
    from signalforge.lab.runner import run_lab_matrix
    from signalforge.report.verification_hub import build_verification_hub, write_manifest
    from signalforge.universe.filters import load_equity_meta, resolve_cohort_tickers

    started = datetime.now(timezone.utc).astimezone().isoformat()
    impl = load_implementation_map()
    n_strat = len(impl.get("strategies", {}))

    if fetch_data:
        tickers = sorted(load_equity_meta().get("tickers", {}).keys())
        if ticker_limit > 0:
            tickers = tickers[:ticker_limit]
        click.echo(f"Fetching OHLCV for {len(tickers)} tickers…")
        from signalforge.data.cache import ParquetCache
        from signalforge.data.fetcher import MarketDataFetcher

        fetcher = MarketDataFetcher(data_source="yfinance")
        cache = ParquetCache()
        for sym in tickers:
            try:
                cache.load_or_fetch(sym, "1d", fetcher, refresh=False)
            except Exception as exc:
                click.echo(f"  skip {sym}: {exc}")

    strategy_ids = _parse_strategy_ids("catalog:all", None, 0)
    cat_by_id = {s["id"]: s for s in load_web_catalog().get("strategies", [])}
    catalog_path = data_dir() / "reports" / "catalog_backtests.json"
    if skip_catalog and catalog_path.exists():
        click.echo(f"\n=== [1/3] Catalog backtest-all — skipped (using {catalog_path.name}) ===")
    else:
        click.echo(f"\n=== [1/3] Catalog backtest-all ({n_strat} strategies) ===")
        catalog_rows: list[dict] = []
        for i, sid in enumerate(strategy_ids, 1):
            cat = cat_by_id.get(sid, {})
            style = cat.get("style") or "swing"
            try:
                result = run_backtest_pipeline(style, sid, cost_model="japan")
                m = result.get("metrics") or {}
                catalog_rows.append(
                    {
                        "id": sid,
                        "style": style,
                        "ticker": result.get("ticker"),
                        "profit_factor": m.get("profit_factor"),
                        "win_rate": m.get("win_rate"),
                        "total_trades": m.get("total_trades"),
                        "total_return_pct": m.get("total_return_pct"),
                        "error": None,
                    }
                )
            except Exception as exc:
                catalog_rows.append({"id": sid, "style": style, "error": str(exc)})
            if i % 20 == 0:
                click.echo(f"  … {i}/{len(strategy_ids)}")
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(
            json.dumps({"results": catalog_rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        click.echo(f"Saved {catalog_path}")

    cohort_cells = 0
    if not skip_cohort:
        click.echo("\n=== [2/3] Strategy × cohort (catalog:all) ===")
        cohort_specs = preset_specs(["prime", "standard", "growth"])
        cohort_specs = [(a, b, {**(c or {}), "exclude_etf": True}) for a, b, c in cohort_specs]

        def _prog(done: int, total: int, sid: str, cid: str) -> None:
            click.echo(f"  cohort {done}/{total} · {sid[:20]} @ {cid}")

        cmp_result = run_comparison_matrix(
            strategy_ids=strategy_ids,
            cohort_specs=cohort_specs,
            cost_model="japan",
            refresh=False,
            catalog_by_id=cat_by_id,
            ticker_limit=ticker_limit,
            progress_cb=_prog,
        )
        cohort_cells = len(cmp_result.get("cells", []))
        (data_dir() / "reports" / "compare_matrix.json").write_text(
            json.dumps(cmp_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    lab_cells = 0
    if not skip_lab:
        click.echo("\n=== [3/3] Lab matrix (all rules × segments) ===")
        rule_ids = resolve_rule_ids("all")

        def resolve_tickers_fn(filt: dict) -> list[str]:
            from signalforge.universe.filters import resolve_cohort_tickers as rct

            t = rct(filt)
            return t[:ticker_limit] if ticker_limit > 0 else t

        lab_result = run_lab_matrix(
            rule_ids,
            preset_specs(["prime", "standard", "growth"]),
            resolve_tickers_fn=resolve_tickers_fn,
        )
        lab_cells = len(lab_result.get("cells", []))
        (data_dir() / "reports" / "lab_matrix.json").write_text(
            json.dumps(lab_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    finished = datetime.now(timezone.utc).astimezone().isoformat()
    write_manifest(
        {
            "started_at": started,
            "finished_at": finished,
            "catalog_strategies": len(strategy_ids),
            "cohort_cells": cohort_cells,
            "lab_cells": lab_cells,
        }
    )
    out = build_verification_hub()
    click.echo(f"\n✅ 検証ハブ: file://{out.resolve()}")
    click.echo("   ブラウザで開くか: uv run signalforge hub open")


@hub.command("open")
def hub_open() -> None:
    """Open verification hub in default browser."""
    import webbrowser

    path = data_dir() / "reports" / "hub" / "index.html"
    if not path.exists():
        raise click.ClickException("Hub not built. Run: uv run signalforge hub build")
    webbrowser.open(path.resolve().as_uri())


@hub.command("refresh")
def hub_refresh() -> None:
    """Rebuild HTML from existing JSON reports only."""
    from signalforge.report.verification_hub import build_verification_hub

    out = build_verification_hub()
    click.echo(f"Refreshed → {out}")


@main.group()
def lab() -> None:
    """Izanami-style workflow: rule palette → rule study → report → allocation → final signals."""


@lab.command("palette")
def lab_palette() -> None:
    """List sell/buy rules (Izanami-like palette)."""
    from signalforge.lab.palette import list_palette_rules

    for r in list_palette_rules():
        tags = ",".join(r.get("tags") or [])
        click.echo(f"{r['id']}: {r['name']} → strategy `{r['strategy']}` [{r.get('style', 'swing')}] ({tags})")


@lab.command("backtest")
@click.option("--rule", "rule_id", required=True, help="Palette rule id (see lab palette)")
@click.option("--cohort", default="prime", show_default=True, help="compare_presets id or universe name")
@click.option("--universe", default=None, help="If set, use universe yaml instead of cohort preset")
@click.option("--ticker-limit", default=0, type=int)
@click.option("--start", default=None, help="Backtest start YYYY-MM-DD")
@click.option("--end", default=None, help="Backtest end YYYY-MM-DD")
@click.option("--output", default=None, type=click.Path(), help="JSON path (default data/reports/lab_<rule>.json)")
@click.option("--use-cache", is_flag=True, help="Load cached study and merge incremental tickers")
@click.option("--save-cache", is_flag=True, help="Save study to data/lab_cache/")
def lab_backtest(
    rule_id: str,
    cohort: str,
    universe: str | None,
    ticker_limit: int,
    start: str | None,
    end: str | None,
    output: str | None,
    use_cache: bool,
    save_cache: bool,
) -> None:
    """Run capital-unconstrained rule study (Izanami backtest stage)."""
    from signalforge.lab.runner import run_rule_study_universe
    from signalforge.universe.filters import get_preset, resolve_cohort_tickers

    if universe:
        tickers = list(load_universe(universe).get("tickers", []))
        cohort_label = universe
    else:
        try:
            p = get_preset(cohort)
            tickers = resolve_cohort_tickers({**(p.get("filter") or {}), "exclude_etf": True})
            cohort_label = p.get("label", cohort)
        except KeyError:
            tickers = list(load_universe(cohort).get("tickers", []))
            cohort_label = cohort
    if ticker_limit > 0:
        tickers = tickers[:ticker_limit]

    override: dict = {}
    if start or end:
        override["backtest"] = {}
        if start:
            override["backtest"]["start_date"] = start
        if end:
            override["backtest"]["end_date"] = end

    click.echo(f"\n=== Lab rule study: {rule_id} · {len(tickers)} tickers ({cohort_label}) ===\n")
    result = run_rule_study_universe(
        rule_id,
        tickers,
        cfg_override=override or None,
        use_cache=use_cache,
        save_cache=save_cache,
    )
    s = result.get("overview") or result.get("summary") or {}
    click.echo(f"【結果概要 — バックテスト】 {result.get('rule_name', rule_id)}")
    click.echo(
        f"Trades={s.get('total_trades')}  Signals={s.get('total_entry_signals')}  "
        f"Fill={s.get('fill_rate', 0):.1%}  Win={s.get('win_rate', 0):.1%}"
    )
    click.echo(
        f"Expectancy={s.get('expectancy_pct', 0):+.3f}%  PF={s.get('profit_factor', 0):.2f}  "
        f"Payoff={s.get('payoff_ratio', 0):.2f}  Median={s.get('median_pnl_pct', 0):+.3f}%"
    )
    click.echo(f"Unfilled: {s.get('unfilled')}  |  PnL buckets: {s.get('pnl_buckets')}")
    ps = result.get("portfolio_sim") or {}
    click.echo(
        f"\n【最適分散投資（近似）】 Final=¥{ps.get('final_equity', 0):,.0f}  "
        f"Return={ps.get('total_return_pct', 0):+.2f}%  "
        f"Trades={ps.get('accepted_trades')} skip={ps.get('skipped_overlap')}"
    )
    click.echo(f"Cache fingerprint: {result.get('fingerprint')}")

    out = Path(output) if output else data_dir() / "reports" / f"lab_{rule_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"\nSaved → {out}")


@lab.command("matrix")
@click.option("--rules", default="all", show_default=True, help="Palette ids or 'all'")
@click.option("--cohorts", default="prime,standard,growth", show_default=True)
@click.option("--ticker-limit", default=0, type=int)
def lab_matrix(rules: str, cohorts: str, ticker_limit: int) -> None:
    """Rule × cohort matrix (Izanami multi-rule verification)."""
    from signalforge.lab.palette import resolve_rule_ids
    from signalforge.lab.runner import run_lab_matrix
    from signalforge.compare.runner import preset_specs
    from signalforge.universe.filters import resolve_cohort_tickers

    rule_ids = resolve_rule_ids(rules)
    cohort_specs = preset_specs([c.strip() for c in cohorts.split(",") if c.strip()])
    for i, (cid, label, filt) in enumerate(cohort_specs):
        cohort_specs[i] = (cid, label, {**(filt or {}), "exclude_etf": True})

    def _resolve(filt: dict) -> list[str]:
        t = resolve_cohort_tickers(filt)
        return t[:ticker_limit] if ticker_limit > 0 else t

    click.echo(f"\n=== Lab matrix: {len(rule_ids)} rules × {len(cohort_specs)} cohorts ===\n")
    result = run_lab_matrix(rule_ids, cohort_specs, resolve_tickers_fn=_resolve)
    out = data_dir() / "reports" / "lab_matrix.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    header = "rule".ljust(24) + "".join(c[0][:10].ljust(12) for c in cohort_specs)
    click.echo(header)
    for rid in rule_ids:
        row = rid[:24].ljust(24)
        for cid, _, _ in cohort_specs:
            cell = next((c for c in result["cells"] if c["rule_id"] == rid and c["cohort_id"] == cid), None)
            ov = (cell.get("overview") or cell.get("summary") or {}) if cell else {}
            exp = ov.get("expectancy_pct")
            row += (f"{exp:+.2f}%" if exp is not None else "—").ljust(12)
        click.echo(row)
    click.echo(f"\nSaved → {out}")


@lab.command("export-csv")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True))
@click.option("--output", default=None, type=click.Path())
def lab_export_csv(input_path: str, output: str | None) -> None:
    """Export all trades from a lab JSON report to CSV."""
    import pandas as pd

    doc = json.loads(Path(input_path).read_text(encoding="utf-8"))
    rows: list[dict] = []
    for block in doc.get("by_ticker") or []:
        rows.extend(block.get("trades") or [])
    if not rows:
        click.echo("No trades in file.")
        return
    out = Path(output) if output else Path(input_path).with_suffix(".trades.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    click.echo(f"Wrote {out} ({len(rows)} rows)")


@lab.command("signals")
@click.option("--rule", "rule_id", required=True)
@click.option("--cohort", default="prime", show_default=True)
@click.option("--ticker-limit", default=0, type=int)
@click.option("--allocate", is_flag=True, help="Show equal-weight allocation (最適分散の近似)")
@click.option("--capital", default=1_000_000.0, type=float)
@click.option("--max-positions", default=5, type=int)
def lab_signals(
    rule_id: str,
    cohort: str,
    ticker_limit: int,
    allocate: bool,
    capital: float,
    max_positions: int,
) -> None:
    """Final-bar signals across universe (Izanami 最終日シグナル)."""
    from signalforge.lab.portfolio import allocate_equal_weight
    from signalforge.lab.runner import run_rule_study_universe
    from signalforge.universe.filters import get_preset, resolve_cohort_tickers

    p = get_preset(cohort)
    tickers = resolve_cohort_tickers({**(p.get("filter") or {}), "exclude_etf": True})
    if ticker_limit > 0:
        tickers = tickers[:ticker_limit]
    result = run_rule_study_universe(rule_id, tickers)
    signals = result.get("final_day_signals") or []
    click.echo(f"\n=== Final signals: {rule_id} · {len(signals)} names ===\n")
    for s in signals:
        click.echo(f"  {s['ticker']}  close={s.get('close')}  rsi={s.get('rsi_14', 0):.1f}")
    if allocate and signals:
        plan = allocate_equal_weight(signals, capital=capital, max_positions=max_positions)
        click.echo(f"\n--- Allocation (¥{capital:,.0f}, max {max_positions}) ---")
        for line in plan:
            click.echo(f"  {line['ticker']}: ¥{line['notional_jpy']:,.0f}")


@main.group()
def cohort() -> None:
    """Compare strategies across Prime/Standard/Growth, sectors, and custom cohorts."""


@cohort.command("presets")
def cohort_presets() -> None:
    """List preset cohorts (market segment, sector, crosses)."""
    from signalforge.universe.filters import list_preset_ids, load_equity_meta

    click.echo("プリセットコホート:")
    for pid, label in list_preset_ids():
        click.echo(f"  {pid}: {label}")
    eq = load_equity_meta()
    n = len(eq.get("tickers", {}))
    click.echo(f"\n登録銘柄メタ: {n} 件（config/universe/japan_equity_meta.yaml）")
    click.echo("自動軸: --by segment | sector_tse")


@cohort.command("run")
@click.option(
    "--strategies",
    default="macd_cross,rsi_reversal,ma_golden_cross",
    show_default=True,
    help="Comma IDs, or catalog:swing / catalog:daytrade",
)
@click.option(
    "--cohorts",
    default="prime,standard,growth",
    show_default=True,
    help="Preset IDs from compare cohorts (comma-separated)",
)
@click.option(
    "--by",
    "by_dimension",
    default=None,
    type=click.Choice(["segment", "sector_tse"]),
    help="Instead of --cohorts, one cohort per market segment or TSE sector",
)
@click.option("--strategy-limit", default=0, type=int, help="Cap strategies when using catalog:*")
@click.option("--ticker-limit", default=0, type=int, help="Cap tickers per cohort (0 = all)")
@click.option("--cost-model", default="japan", type=COST_MODEL_CHOICE)
@click.option("--refresh", is_flag=True, help="Re-fetch OHLCV per ticker")
@click.option("--exclude-etf", is_flag=True, default=True, show_default=True)
def cohort_run(
    strategies: str,
    cohorts: str,
    by_dimension: str | None,
    strategy_limit: int,
    ticker_limit: int,
    cost_model: str,
    refresh: bool,
    exclude_etf: bool,
) -> None:
    """Backtest strategy × cohort matrix; write data/reports/compare_matrix.json."""
    from signalforge.compare.runner import preset_specs, run_comparison_matrix
    from signalforge.universe.filters import cohorts_by_dimension

    strategy_ids = _parse_strategy_ids(strategies, None, strategy_limit)
    if not strategy_ids:
        raise click.ClickException("No strategies selected")

    if by_dimension:
        cohort_specs = cohorts_by_dimension(by_dimension)
    else:
        cohort_specs = preset_specs([c.strip() for c in cohorts.split(",") if c.strip()])

    if exclude_etf:
        cohort_specs = [
            (cid, label, {**(filt or {}), "exclude_etf": True}) for cid, label, filt in cohort_specs
        ]

    cat_by_id = {s["id"]: s for s in load_web_catalog().get("strategies", [])}
    click.echo(
        f"\n=== Compare: {len(strategy_ids)} strategies × {len(cohort_specs)} cohorts "
        f"(cost={cost_model}) ===\n"
    )

    def _prog(done: int, total: int, sid: str, cid: str) -> None:
        click.echo(f"  {done}/{total} · {sid[:24]} @ {cid}")

    result = run_comparison_matrix(
        strategy_ids=strategy_ids,
        cohort_specs=cohort_specs,
        cost_model=cost_model,
        refresh=refresh,
        catalog_by_id=cat_by_id,
        ticker_limit=ticker_limit,
        progress_cb=_prog,
    )

    out_dir = data_dir() / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "compare_matrix.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    pivot: dict[str, dict[str, float | None]] = {}
    for cell in result["cells"]:
        sid = cell["strategy"]
        cid = cell["cohort_id"]
        pivot.setdefault(sid, {})[cid] = cell.get("summary", {}).get("median_profit_factor")

    click.echo(f"Saved → {out_path}\n")
    click.echo("Median PF (strategy × cohort):")
    cohort_ids = [c[0] for c in cohort_specs]
    header = "strategy".ljust(28) + "".join(c[:10].ljust(12) for c in cohort_ids)
    click.echo(header)
    for sid in strategy_ids:
        row = sid[:28].ljust(28)
        for cid in cohort_ids:
            pf = pivot.get(sid, {}).get(cid)
            row += (f"{pf:.2f}" if pf is not None else "—").ljust(12)
        click.echo(row)


@main.group()
def strategies() -> None:
    """Web-collected strategy catalog (sources + implementation status)."""


@strategies.command("catalog")
@click.option("--implemented-only", is_flag=True, help="Show only implemented strategies")
@click.option("--candidates-only", is_flag=True, help="Show only not-yet-implemented candidates")
@click.option("--style", default=None, type=click.Choice(["swing", "daytrade"]))
@click.option("--tag", default=None, help="Filter by tag (e.g. vwap, ichimoku, breakout)")
@click.option("--json", "as_json", is_flag=True, help="Print raw YAML as JSON")
def strategies_catalog(
    implemented_only: bool,
    candidates_only: bool,
    style: str | None,
    tag: str | None,
    as_json: bool,
) -> None:
    """List strategies gathered from blogs, YouTube, X, broker sites, etc."""
    cat = load_web_catalog()
    meta = cat.get("meta", {})
    items = list(cat.get("strategies", []))
    if implemented_only:
        items = [s for s in items if s.get("implemented")]
    if candidates_only:
        items = [s for s in items if not s.get("implemented")]
    if style:
        items = [s for s in items if s.get("style") == style]
    if tag:
        items = [s for s in items if tag in (s.get("tags") or [])]

    if as_json:
        click.echo(
            json.dumps(
                {"meta": meta, "updated": cat.get("updated"), "strategies": items},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    all_items = cat.get("strategies", [])
    impl_n = sum(1 for s in all_items if s.get("implemented"))
    cand_n = len(all_items) - impl_n
    updated = meta.get("last_collection") or cat.get("updated", "?")
    click.echo(f"Web strategy catalog（収集日 {updated}）")
    click.echo(f"  全 {len(all_items)} 件 · 実装済み {impl_n} · 候補 {cand_n}")
    if style or tag or implemented_only or candidates_only:
        click.echo(f"  表示中: {len(items)} 件\n")
    else:
        click.echo("")

    for s in items:
        flag = "✓" if s.get("implemented") else "·"
        tags = ",".join(s.get("tags") or [])
        tag_s = f" ({tags})" if tags else ""
        click.echo(f"{flag} {s.get('id')}: {s.get('name')} [{s.get('style', '?')}]{tag_s}")
        for src in s.get("sources", []):
            click.echo(f"    - {src.get('type', '?')}: {src.get('title', '')} → {src.get('url', '')}")


@strategies.command("media")
@click.option("--category", default=None, help="Filter by category (broker, media, screener, …)")
def strategies_media(category: str | None) -> None:
    """List registered media outlets for strategy harvesting."""
    reg = load_media_sources()
    outlets = list(reg.get("outlets", []))
    if category:
        outlets = [o for o in outlets if o.get("category") == category]
    fetch_n = 0
    skip_n = 0
    for o in outlets:
        policy = o.get("fetch_policy") or "fetch"
        urls = o.get("urls") or []
        if policy == "skip":
            skip_n += len(urls)
            flag = "skip"
        else:
            fetch_n += len(urls)
            flag = policy if policy != "fetch" else "http"
        click.echo(f"{o.get('id')}: {o.get('name')} [{o.get('category')}] — {len(urls)} URL ({flag})")
    meta = reg.get("meta", {})
    click.echo(f"\n台帳 v{meta.get('version', '?')} · 取得対象 URL 約 {fetch_n} · 手動/skip {skip_n}")


@strategies.command("harvest")
@click.option("--youtube", is_flag=True, help="Also fetch YouTube subtitles (pip install youtube-transcript-api)")
@click.option("--max-urls", default=0, type=int, help="Limit HTTP fetches (0 = all registered URLs)")
def strategies_harvest(youtube: bool, max_urls: int) -> None:
    """Fetch media registry URLs and write keyword hits to data/strategy_harvest/."""
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts" / "collect_strategy_mentions.py"
    cmd = [sys.executable, str(script)]
    if youtube:
        cmd.append("--youtube")
    if max_urls:
        cmd.extend(["--max-urls", str(max_urls)])
    subprocess.run(cmd, check=False)
    cat = load_web_catalog()
    meta = cat.get("meta", {}).get("collection", {})
    click.echo(f"\nカタログ件数: {len(cat.get('strategies', []))}")
    status_line = (meta.get("honest_status") or "").strip().split("\n")[0]
    click.echo(f"収集ポリシー: {status_line}")


@strategies.command("collect-max")
@click.option("--youtube", is_flag=True, help="Include YouTube subtitles in harvest")
def strategies_collect_max(youtube: bool) -> None:
    """Harvest all media URLs, expand catalog, regenerate implementation map."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    py = sys.executable

    subprocess.run([py, str(root / "scripts" / "collect_strategy_mentions.py")], check=False)
    if youtube:
        subprocess.run([py, str(root / "scripts" / "collect_strategy_mentions.py"), "--youtube"], check=False)
    subprocess.run([py, str(root / "scripts" / "expand_strategy_catalog.py")], check=True)
    subprocess.run([py, str(root / "scripts" / "generate_implementation_map.py")], check=True)
    subprocess.run([py, str(root / "scripts" / "sync_catalog_implemented.py")], check=True)
    cat = load_web_catalog()
    click.echo(f"\n収集完了: カタログ {len(cat.get('strategies', []))} 件 · implementation_map 同期済み")


@strategies.command("backtest-all")
@click.option("--ticker", default=None, help="Override ticker (default: market default e.g. 7203.T)")
@click.option("--limit", default=0, type=int, help="Max strategies (0 = all in implementation_map)")
@click.option("--cost-model", default="japan", type=click.Choice(["japan", "alpaca", "zero"]))
def strategies_backtest_all(ticker: str | None, limit: int, cost_model: str) -> None:
    """Backtest every catalog strategy with an implementation mapping."""
    impl = load_implementation_map().get("strategies", {})
    cat_by_id = {s["id"]: s for s in load_web_catalog().get("strategies", [])}
    ids = list(impl.keys())
    if limit > 0:
        ids = ids[:limit]

    out_dir = data_dir() / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "catalog_backtests.json"
    rows: list[dict] = []
    ok = err = 0

    for sid in ids:
        entry = impl[sid]
        cat = cat_by_id.get(sid, {})
        style = entry.get("backtest_style") or cat.get("style") or entry.get("catalog_style") or "swing"
        override = {"ticker": ticker} if ticker else None
        try:
            result = run_backtest_pipeline(
                style,
                sid,
                refresh_data=False,
                cost_model=cost_model,
                cfg_override=override,
            )
            m = result.get("metrics") or {}
            rows.append(
                {
                    "id": sid,
                    "style": style,
                    "ticker": result.get("ticker"),
                    "profit_factor": m.get("profit_factor"),
                    "win_rate": m.get("win_rate"),
                    "total_trades": m.get("total_trades"),
                    "total_return_pct": m.get("total_return_pct"),
                    "approximation": entry.get("approximation"),
                    "error": None,
                }
            )
            ok += 1
        except Exception as exc:
            rows.append({"id": sid, "style": style, "error": str(exc)})
            err += 1

    out_path.write_text(json.dumps({"results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"Backtest matrix: ok={ok} err={err} → {out_path}")
    ranked = sorted(
        [r for r in rows if r.get("profit_factor") is not None],
        key=lambda x: float(x.get("profit_factor") or 0),
        reverse=True,
    )[:10]
    if ranked:
        click.echo("\nTop PF (single-ticker run):")
        for r in ranked:
            click.echo(
                f"  {r['id']}: PF={float(r['profit_factor']):.2f} "
                f"trades={r.get('total_trades')} return={r.get('total_return_pct')}%"
            )


@strategies.command("stats")
def strategies_stats() -> None:
    """Summarize catalog by style, tags, and source type."""
    cat = load_web_catalog()
    items = cat.get("strategies", [])
    by_style: dict[str, int] = {}
    by_tag: dict[str, int] = {}
    by_src: dict[str, int] = {}
    for s in items:
        st = s.get("style", "unknown")
        by_style[st] = by_style.get(st, 0) + 1
        for t in s.get("tags") or []:
            by_tag[t] = by_tag.get(t, 0) + 1
        for src in s.get("sources") or []:
            k = src.get("type", "?")
            by_src[k] = by_src.get(k, 0) + 1
    impl = sum(1 for s in items if s.get("implemented"))
    click.echo(f"Catalog: {len(items)} strategies ({impl} implemented, {len(items) - impl} candidates)\n")
    click.echo("By style:")
    for k, v in sorted(by_style.items(), key=lambda x: -x[1]):
        click.echo(f"  {k}: {v}")
    click.echo("\nTop tags:")
    for k, v in sorted(by_tag.items(), key=lambda x: -x[1])[:15]:
        click.echo(f"  {k}: {v}")
    click.echo("\nSource types:")
    for k, v in sorted(by_src.items(), key=lambda x: -x[1]):
        click.echo(f"  {k}: {v}")


@main.command()
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
@click.option("--strategy", default=None)
@click.option("--refresh", is_flag=True)
@click.option("--ml-filter", is_flag=True)
@click.option("--cost-model", default="japan", type=COST_MODEL_CHOICE, help="Trading cost model")
def backtest(style: str, strategy: str | None, refresh: bool, ml_filter: bool, cost_model: str) -> None:
    """Run backtest with trade journal."""
    cfg = load_style_config(style)
    strat = strategy or cfg.get("strategy", "ema_pullback")
    override = champion_cfg_override(style, strat, cfg)
    result = run_backtest_pipeline(
        style,
        strategy,
        refresh,
        ml_filter,
        cost_model=cost_model,
        cfg_override=override,
    )
    click.echo(f"\n=== Backtest: {result['style']} / {result['strategy']} ===")
    click.echo(f"Ticker: {result.get('ticker', '?')}")
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
    optimized_macd = CHAMPION_MACD_PARAMS

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

    data = root / "data" / "7203.T_1d.pkl"
    click.echo(
        f"Data cache: {'OK' if data.is_file() else 'MISSING — run: uv run signalforge fetch --ticker 7203.T --timeframe 1d'}"
    )

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
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
@click.option("--strategy", default=None)
@click.option("--cost-model", default="japan", type=COST_MODEL_CHOICE)
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
@click.option("--cost-model", default=None, type=COST_MODEL_CHOICE)
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
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
@click.option("--strategy", default=None)
@click.option("--refresh/--no-refresh", default=True, help="Fetch latest market data")
@click.option("--cost-model", default=None, type=COST_MODEL_CHOICE)
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
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
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
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
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
