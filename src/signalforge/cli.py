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
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


@main.command()
@click.option("--ticker", default=None, help="Single ticker (default: 7203.T)")
@click.option("--universe", default=None, help="Universe yaml name (e.g. japan_liquid)")
@click.option("--cohort", default=None, help="Compare preset id (e.g. tse_all, prime) — ETF 除外")
@click.option("--timeframe", default="1d", type=click.Choice(["1d", "1h", "1m", "2m", "5m", "15m"]))
@click.option("--source", default="auto", type=click.Choice(["auto", "yfinance", "alpaca"]))
@click.option("--refresh", is_flag=True, help="キャッシュを捨てて全期間を取り直す")
@click.option("--update", "update_cache", is_flag=True, help="キャッシュの末尾以降だけ足す（無ければ全期間）")
@click.option("--with-correlations", is_flag=True, help="Also fetch 1321.T / 1570.T")
@click.option("--workers", default=1, show_default=True, type=int, help="並列取得数（--cohort 向け）")
@click.option("--paper-books", is_flag=True, help="保存済み分散ペーパー口座の銘柄（和集合）")
def fetch(
    ticker: str | None,
    universe: str | None,
    cohort: str | None,
    timeframe: str,
    source: str,
    refresh: bool,
    update_cache: bool,
    with_correlations: bool,
    workers: int,
    paper_books: bool,
) -> None:
    """Fetch and cache market data (Japan: yfinance *.T)."""
    import os

    if paper_books:
        from signalforge.paper.diversified import list_diversified_paper_books

        tickers = sorted({t for b in list_diversified_paper_books() for t in (b.tickers or [])})
        if not tickers:
            raise click.ClickException("分散ペーパー口座がありません。")
    elif cohort:
        from signalforge.paper.diversified import resolve_universe_tickers

        tickers = resolve_universe_tickers(cohort, 0)
    elif universe:
        tickers = list(load_universe(universe).get("tickers", []))
    else:
        default = load_market_config("japan").get("default_ticker", "7203.T")
        tickers = [ticker or default]

    if source == "auto":
        source = "yfinance"
        if tickers and not str(tickers[0]).endswith(".T"):
            if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"):
                source = "alpaca"
    if refresh and update_cache:
        raise click.ClickException("--refresh と --update は同時に指定できません。")
    fetcher = MarketDataFetcher(data_source=source)
    cache = ParquetCache()

    def _load(sym: str):
        if update_cache:
            return cache.update(sym, timeframe, fetcher)
        return cache.load_or_fetch(sym, timeframe, fetcher, refresh=bool(refresh))

    if workers > 1 and len(tickers) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _one(sym: str) -> tuple[str, int | None, str]:
            try:
                df = _load(sym)
                return sym, len(df), ""
            except Exception as exc:
                return sym, None, str(exc)

        ok = failed = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, fut in enumerate(as_completed([pool.submit(_one, s) for s in tickers]), start=1):
                sym, n, err = fut.result()
                if n is None:
                    failed += 1
                    click.echo(f"✗ {sym}: {err}")
                else:
                    ok += 1
                if i % 250 == 0:
                    click.echo(f"… {i}/{len(tickers)}")
        click.echo(f"Cached {ok} / {len(tickers)} ({timeframe}, {source}) · 失敗 {failed}")
    else:
        for sym in tickers:
            df = _load(sym)
            click.echo(f"Cached {sym} {timeframe} ({source}): {len(df)} bars → {cache.path(sym, timeframe)}")
    if with_correlations:
        for sym in load_market_config("japan").get("correlation_tickers", []):
            cdf = _load(sym)
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
        if want_style is None and spec.split(":", 1)[1].strip() in ("all", ""):
            from signalforge.experiments.order import sort_strategies_for_campaign

            cat_by_id = {s["id"]: s for s in load_web_catalog().get("strategies", []) if s.get("id")}
            ids = sort_strategies_for_campaign(ids, cat_by_id)
        return ids
    ids = [x.strip() for x in spec.split(",") if x.strip()]
    if limit > 0:
        ids = ids[:limit]
    return ids


@main.group()
def universe() -> None:
    """TSE listed issues (JPX official master)."""


@universe.command("refresh")
@click.option("--include-all-products", is_flag=True, help="Include ETF/REIT/foreign (not just domestic equity)")
def universe_refresh(include_all_products: bool) -> None:
    """Download JPX 東証上場銘柄一覧 → data/universe/tse_listing.json."""
    from signalforge.universe.tse_listing import refresh_tse_listing

    doc = refresh_tse_listing(include_non_domestic_equity=include_all_products)
    click.echo(f"✓ {doc['n_tickers']} 銘柄 · {doc['source_url']}")
    click.echo(f"  → {data_dir() / 'universe' / 'tse_listing.json'}")


@universe.command("count")
def universe_count() -> None:
    """Show cached TSE listing counts by segment."""
    from signalforge.universe.tse_listing import load_tse_listing

    doc = load_tse_listing(refresh=False)
    rows = doc.get("tickers") or []
    by: dict[str, int] = {}
    for r in rows:
        seg = r.get("segment") or r.get("market") or "?"
        by[seg] = by.get(seg, 0) + 1
    click.echo(f"Listing fetched: {doc.get('fetched_at', '?')}")
    for k, v in sorted(by.items(), key=lambda x: -x[1]):
        click.echo(f"  {k}: {v}")
    click.echo(f"Total rows: {len(rows)}")


@main.group()
def hub() -> None:
    """Run all verifications and build ranking/chart hub."""


@hub.command("build")
@click.option("--fetch-data/--no-fetch-data", default=False, help="Fetch OHLCV for cohort tickers before build")
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
        from signalforge.compare.runner import default_universe_tickers

        tickers = default_universe_tickers(ticker_limit, refresh_listing=False)
        click.echo(f"Fetching OHLCV for {len(tickers)} TSE tickers (JPX list)…")
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
    catalog_rows: list[dict] = []
    cohort_cells = 0
    cmp_result: dict | None = None

    if skip_cohort and not skip_catalog:
        from signalforge.compare.runner import build_universe_catalog_rows, default_universe_tickers

        uni = default_universe_tickers(ticker_limit)
        click.echo(
            f"\n=== [1/3] Catalog · {n_strat} strategies × {len(uni)} 銘柄 (median PF) ==="
        )

        def _cat_prog(i: int, total: int, sid: str) -> None:
            click.echo(f"  … {i}/{total} · {sid[:24]}")

        catalog_rows = build_universe_catalog_rows(
            strategy_ids=strategy_ids,
            tickers=uni,
            cost_model="japan",
            catalog_by_id=cat_by_id,
            progress_cb=_cat_prog,
        )
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(
            json.dumps(
                {
                    "meta": {"evaluation": "multi_ticker_median", "n_tickers": len(uni)},
                    "results": catalog_rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        click.echo(f"Saved {catalog_path}")
    elif skip_catalog and catalog_path.exists():
        click.echo(f"\n=== [1/3] Catalog — skipped (using {catalog_path.name}) ===")
    else:
        click.echo(
            f"\n=== [1/3] Catalog — コホート行列完了後に全銘柄集計で生成 ==="
        )

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
        if not skip_catalog:
            from signalforge.compare.runner import catalog_rows_from_compare_matrix

            catalog_rows = catalog_rows_from_compare_matrix(cmp_result)
            n_pool = max((r.get("n_tickers") or 0) for r in catalog_rows) if catalog_rows else 0
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            catalog_path.write_text(
                json.dumps(
                    {
                        "meta": {
                            "evaluation": "multi_ticker_median",
                            "n_tickers": n_pool,
                            "source": "compare_matrix_pooled",
                        },
                        "results": catalog_rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            click.echo(f"Saved {catalog_path} ({len(catalog_rows)} strategies · pooled cohort tickers)")

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


@main.group("alt-data")
def alt_data_group() -> None:
    """Fetch sector / earnings datasets and re-run strategies that depend on them."""


@alt_data_group.command("status")
def alt_data_status_cmd() -> None:
    """Show alt-data cache coverage and strategies wired to real datasets."""
    from signalforge.alt_data.deps import PLANNED_DATASETS, strategies_using_dataset
    from signalforge.alt_data.status import alt_data_status

    st = alt_data_status()
    click.echo("=== 代替データ（OHLCV 以外）===")
    click.echo(f"業種指数: {st['sector_indices_built']} / {st['sector_groups']} 業種")
    click.echo(f"決算日ファイル: {st['earnings_files']} / {st['tse_tickers']} 銘柄")
    click.echo(f"信用残（J-Quants）: {st.get('credit_margin_files', 0)} 銘柄")
    click.echo(f"data_deps 付き戦略: {st['strategies_with_data_deps']}")
    click.echo(f"まだ approximation の戦略: {st['strategies_still_approximation']}")
    click.echo("\n--- データセット別の戦略数 ---")
    for key in ("sector_index", "earnings", "credit_balance"):
        n = len(strategies_using_dataset(key))
        if n:
            click.echo(f"  {key}: {n}")
    click.echo("\n--- 未実装（要 API / スクレイプ）---")
    for k, msg in PLANNED_DATASETS.items():
        click.echo(f"  {k}: {msg}")


@alt_data_group.command("fetch")
@click.option("--sectors", is_flag=True, help="業種別 EW 指数（キャッシュ OHLCV から構築）")
@click.option(
    "--earnings",
    is_flag=True,
    help="銘柄ごと決算日（JQUANTS_API_KEY あれば J-Quants、なければ yfinance）",
)
@click.option("--yahoo", is_flag=True, help="決算日を yfinance から取る。無料J-Quantsの12週間遅れは使わない")
@click.option("--all", "fetch_all", is_flag=True, help="--sectors と --earnings")
@click.option("--refresh", is_flag=True, help="既存ファイルも再取得")
@click.option("--limit", default=0, type=int, help="earnings / jquants-credit の銘柄数上限（0=全 TSE）")
@click.option(
    "--jquants-credit",
    is_flag=True,
    help="J-Quants 信用残（要 JQUANTS_API_KEY）",
)
def alt_data_fetch_cmd(
    sectors: bool,
    earnings: bool,
    yahoo: bool,
    fetch_all: bool,
    refresh: bool,
    limit: int,
    jquants_credit: bool,
) -> None:
    """Collect alt datasets under data/alt/."""
    from signalforge.alt_data.earnings import fetch_earnings_universe
    from signalforge.alt_data.sector_index import build_all_sector_indices
    from signalforge.universe.tse_listing import list_tse_tickers

    if fetch_all:
        sectors = earnings = True
    if not sectors and not earnings and not jquants_credit:
        raise click.ClickException(
            "--sectors / --earnings / --jquants-credit / --all のいずれかを指定"
        )

    if sectors:
        click.echo("業種指数を構築中…")

        def _sp(i: int, n: int, name: str) -> None:
            if i % 5 == 0 or i == n:
                click.echo(f"  [{i}/{n}] {name}")

        stats = build_all_sector_indices(refresh=refresh, progress_cb=_sp)
        click.echo(f"✅ 業種指数: {stats['sectors_built']} / {stats['sectors_total']}")

    if earnings:
        import os

        tickers = list_tse_tickers()
        if limit > 0:
            tickers = tickers[:limit]
        use_jq = bool((os.getenv("JQUANTS_API_KEY") or "").strip()) and not yahoo
        src = "J-Quants earnings-calendar" if use_jq else "yfinance"
        click.echo(f"決算日を取得中… ({len(tickers)} 銘柄, {src})")

        def _ep(i: int, n: int, sym: str) -> None:
            if i % 200 == 0 or i == n:
                click.echo(f"  [{i}/{n}] {sym}")

        if use_jq:
            from signalforge.alt_data.earnings_jquants import fetch_earnings_jquants_universe

            stats = fetch_earnings_jquants_universe(tickers, refresh=refresh, progress_cb=_ep)
        else:
            stats = fetch_earnings_universe(tickers, refresh=refresh, progress_cb=_ep)
        click.echo(f"✅ 決算日ファイル: {stats['with_dates']} / {stats['tickers']} に日付あり")

    if jquants_credit:
        from signalforge.alt_data.credit_balance import fetch_margin_universe

        tickers = list_tse_tickers()
        if limit > 0:
            tickers = tickers[:limit]
        click.echo(f"J-Quants 信用残を取得中… ({len(tickers)} 銘柄)")

        def _cp(i: int, n: int, sym: str) -> None:
            if i % 50 == 0 or i == n:
                click.echo(f"  [{i}/{n}] {sym}")

        stats = fetch_margin_universe(tickers, refresh=refresh, progress_cb=_cp)
        click.echo(
            f"✅ 信用残: {stats['with_margin']} / {stats['tickers']} "
            f"(errors {stats.get('errors', 0)})"
        )


@alt_data_group.command("jquants-test")
def alt_data_jquants_test_cmd() -> None:
    """Verify JQUANTS_API_KEY with one margin-interest request (72030)."""
    from signalforge.alt_data.jquants_client import JQuantsError, test_connection

    try:
        info = test_connection()
    except JQuantsError as e:
        raise click.ClickException(str(e)) from e
    click.echo(
        f"✅ J-Quants 接続 OK（{info['code']} master={info['master_rows']} "
        f"決算カレンダー={info['earnings_calendar_rows']}）"
    )
    if not info.get("margin_interest_available"):
        click.echo(
            "⚠️  信用残 API (/markets/margin-interest) は現在のプランでは利用不可です。"
            " credit_balance_contrarian には有料プランが必要です。"
        )
        if info.get("margin_note"):
            click.echo(f"    ({info['margin_note'][:120]})")


@alt_data_group.command("refresh-trusted")
@click.option("--fetch-earnings", is_flag=True, help="J-Quants/yfinance で決算日を先に取得")
@click.option("--limit", default=0, type=int, help="決算 fetch の銘柄上限（0=全件）")
@click.option("--run-experiments", is_flag=True, help="invalidate 後に experiments run を起動")
def alt_data_refresh_trusted_cmd(fetch_earnings: bool, limit: int, run_experiments: bool) -> None:
    """本データが揃った戦略だけ JSON を消して再BT可能にする。"""
    import os
    import subprocess

    from signalforge.alt_data.trust import _coverage_snapshot, strategies_ready_for_rerun
    from signalforge.universe.tse_listing import list_tse_tickers

    if fetch_earnings:
        tickers = list_tse_tickers()
        if limit > 0:
            tickers = tickers[:limit]
        use_jq = bool((os.getenv("JQUANTS_API_KEY") or "").strip())
        if use_jq:
            from signalforge.alt_data.earnings_jquants import fetch_earnings_jquants_universe

            click.echo(f"決算日取得（J-Quants）… {len(tickers)} 銘柄")
            fetch_earnings_jquants_universe(tickers, refresh=True)
        else:
            from signalforge.alt_data.earnings import fetch_earnings_universe

            click.echo(f"決算日取得（yfinance）… {len(tickers)} 銘柄")
            fetch_earnings_universe(tickers, refresh=True)
        _coverage_snapshot.cache_clear()

    ready = strategies_ready_for_rerun()
    click.echo(f"再BT可能（代理なし・data 充足）: {len(ready)} 戦略")
    for sid in ready:
        click.echo(f"  · {sid}")

    from signalforge.alt_data.invalidate import invalidate_trusted_alt_strategies

    touched = invalidate_trusted_alt_strategies()
    click.echo(f"削除した experiment JSON: {len(touched)} 件")

    if run_experiments and touched:
        click.echo("experiments run を起動…")
        subprocess.Popen(
            [
                "uv",
                "run",
                "signalforge",
                "experiments",
                "run",
                "--ignore-schedule",
                "--workers",
                "8",
            ],
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        click.echo("バックグラウンドで開始しました。")
    elif touched:
        click.echo("再BT: uv run signalforge experiments run --ignore-schedule --workers 8")


@alt_data_group.command("invalidate-experiments")
def alt_data_invalidate_cmd() -> None:
    """Remove completed experiment JSON for strategies with data_deps (再BT用)."""
    from signalforge.alt_data.invalidate import invalidate_alt_data_strategies

    touched = invalidate_alt_data_strategies()
    if not touched:
        click.echo("data_deps 付き戦略がありません。")
        return
    click.echo(f"削除・再BT対象: {len(touched)} 戦略")
    for sid in touched:
        click.echo(f"  · {sid}")
    click.echo("\n再実行例:")
    click.echo("  uv run signalforge experiments run --ignore-schedule --workers 8")


@main.group()
def experiments() -> None:
    """Multi-axis TSE backtest campaigns (universe / segment / sector)."""


@experiments.command("plan")
def experiments_plan_cmd() -> None:
    """Show experiment design (one BT pass → many aggregations)."""
    from signalforge.experiments.runner import load_plan

    plan = load_plan()
    meta = plan.get("meta", {})
    click.echo(meta.get("title", "Experiment plan"))
    click.echo(meta.get("description", "").strip())
    click.echo(f"\n戦略: {plan.get('strategies')}")
    click.echo("\n集計軸:")
    for agg in plan.get("aggregations") or []:
        click.echo(f"  · {agg.get('id')}: {agg.get('label')} ({agg.get('group')})")
    click.echo("\n実行: uv run signalforge experiments run")
    click.echo("状態: uv run signalforge experiments status")


def _print_experiment_progress(scan: dict) -> None:
    from signalforge.experiments.scan import format_progress_bar

    ov = scan.get("overall") or {}
    n_done = int(ov.get("strategies_complete") or len(scan.get("complete") or []))
    n_plan = int(ov.get("strategies_planned") or scan.get("total_planned") or 0)
    pool = scan.get("n_tickers_pool") or "—"
    click.echo(f"TSE 実験  ·  銘柄プール {pool}")
    click.echo("")
    click.echo("【全体】")
    click.echo(
        f"  戦略  {format_progress_bar(float(ov.get('strategy_overall_pct') or 0))}  "
        f"（{ov.get('strategy_equiv', n_done):.2f} / {n_plan} 戦略相当）"
    )
    if ov.get("ticker_jobs_total"):
        click.echo(
            f"  銘柄BT {format_progress_bar(float(ov.get('ticker_overall_pct') or 0))}  "
            f"（{ov.get('ticker_jobs_done'):,} / {ov.get('ticker_jobs_total'):,} 回）"
        )
    if ov.get("active_strategy_id"):
        ad, at = ov.get("active_n_done"), ov.get("active_n_target")
        ap = 100.0 * int(ad) / max(1, int(at)) if at else 0
        click.echo(
            f"\n【いま実行中】 `{ov['active_strategy_id']}`  "
            f"{ad}/{at} ({ap:.1f}%)"
        )
    stale = ov.get("stale_checkpoints") or []
    if stale:
        click.echo("\n【checkpoint 保留（後で再開）】")
        for row in stale:
            tgt = max(1, int(row.get("n_target") or 1))
            done = int(row.get("n_done") or 0)
            click.echo(f"  · {row.get('strategy_id')}: {done}/{tgt} ({100.0 * done / tgt:.1f}%)")
    click.echo("")


@experiments.command("status")
def experiments_status_cmd() -> None:
    """Progress of the TSE experiment campaign."""
    from signalforge.experiments.scan import scan_campaign_progress

    scan = scan_campaign_progress()
    _print_experiment_progress(scan)
    n_done = len(scan["complete"])
    n_plan = int(scan["total_planned"])
    if scan["complete"]:
        from signalforge.report.metrics_ja import EXPECTANCY, PROFIT_FACTOR, TSE_TABLE_NOTE

        click.echo(f"完了（{EXPECTANCY} 上位 5）:")
        for row in scan["complete"][:5]:
            exp = row.get("expectancy_pct")
            pf = row.get("profit_factor")
            exp_s = f"{float(exp):+.3f}%" if exp is not None else "—"
            pf_s = f"{float(pf):.2f}" if pf is not None else "—"
            click.echo(f"  · {row['strategy_id']}: {EXPECTANCY} {exp_s}  {PROFIT_FACTOR} {pf_s}")
        click.echo(f"  ※ {TSE_TABLE_NOTE}")
    if scan["in_progress"]:
        click.echo("実行中・途中:")
        for row in scan["in_progress"]:
            tgt = max(1, int(row.get("n_target") or 1))
            done = int(row.get("n_done") or 0)
            pct = 100.0 * done / tgt
            tag = " ← 実行中" if row.get("active") else "（checkpoint 保留）"
            click.echo(f"  · {row['strategy_id']}: {done}/{tgt} ({pct:.1f}%){tag}")
    man = scan.get("manifest") or {}
    if man.get("finished_at"):
        click.echo(f"\n直近 manifest（{man.get('finished_at')}）:")
        click.echo(
            f"  new={man.get('completed')} skip={man.get('skipped_complete')} "
            f"fail={man.get('failed')} early_stop={man.get('stopped_early', 0)}"
        )
    elif not scan["complete"] and not scan["in_progress"]:
        click.echo("未実行（experiments run）")


@experiments.command("watch")
@click.option("--interval", default=5, show_default=True, help="更新間隔（秒）")
@click.option("--classic", is_flag=True, help="status 形式を毎回スクロール表示（旧）")
@click.option("--no-alt-screen", is_flag=True, help="代替画面を使わず全画面クリア")
def experiments_watch_cmd(interval: int, classic: bool, no_alt_screen: bool) -> None:
    """tqdm 風に同一画面で進捗更新（Ctrl+C で監視のみ終了）。"""
    if not classic:
        from signalforge.experiments.live_progress import run_live_watch

        run_live_watch(interval=float(interval), use_alt_screen=not no_alt_screen)
        return

    import time

    from signalforge.experiments.scan import scan_campaign_progress

    try:
        while True:
            click.echo("\033[2J\033[H", nl=False)
            click.echo(f"TSE 実験進捗  （{interval}s 更新 · Ctrl+C で終了）\n")
            scan = scan_campaign_progress()
            _print_experiment_progress(scan)
            click.echo(f"\n次回更新まで {interval}s …")
            time.sleep(max(1, interval))
    except KeyboardInterrupt:
        click.echo("\nwatch 終了")


@experiments.command("supervise")
@click.option("--interval", default=60, show_default=True, help="BT 停止検知の間隔（秒）")
@click.option(
    "--mode",
    type=click.Choice(["auto", "campaign", "metrics"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="auto=指標差し替え優先、metrics=--refresh-metrics 固定",
)
@click.option("--workers", default=0, type=int, help="再開時 workers（0=schedule/CPU）")
@click.option("--once", is_flag=True, help="1 回だけ確認（未実行なら起動して終了）")
def experiments_supervise_cmd(interval: int, mode: str, workers: int, once: bool) -> None:
    """BT プロセスを監視し、止まっていれば experiments run を再開（Ctrl+C で監視のみ終了）。"""
    from signalforge.experiments.supervisor import RunMode, supervise_loop

    supervise_loop(
        interval_sec=float(interval),
        mode=mode.lower(),  # type: ignore[arg-type]
        workers=workers,
        run_once=once,
    )


@experiments.command("supervisor-status")
def experiments_supervisor_status_cmd() -> None:
    """監視・BT プロセスの状態（experiments supervise 用）。"""
    from signalforge.experiments.supervisor import supervisor_status

    st = supervisor_status()
    work = st["work"]
    click.echo(f"BT 実行中: {'はい' if st['run_alive'] else 'いいえ'}  pids={st['run_pids']}")
    click.echo(f"作業: {'あり' if work.needs_run else 'なし'} — {work.reason}")
    if work.needs_run:
        click.echo(
            f"  完了 {work.n_complete}/{work.n_planned} · checkpoint {work.n_in_progress} · "
            f"指標待ち {work.n_metrics_pending}"
        )
    click.echo(f"監視ログ: {st['supervisor_log']}")
    click.echo(f"BT ログ: {st['run_log']}")


@experiments.command("capital")
@click.option("--initial-cash-jpy", default=None, type=float)
@click.option("--max-position-pct", default=None, type=float)
@click.option("--min-cash-reserve-pct", default=None, type=float)
def experiments_capital_cmd(
    initial_cash_jpy: float | None,
    max_position_pct: float | None,
    min_cash_reserve_pct: float | None,
) -> None:
    """Show effective TSE experiment capital settings and stale strategy counts."""
    from signalforge.experiments.runner import (
        list_strategies_needing_capital_refresh,
        load_plan,
        resolve_campaign_backtest_capital,
    )

    plan = load_plan()
    strategy_ids = _parse_strategy_ids(plan.get("strategies", "catalog:all"), None, 0)
    record, _ = resolve_campaign_backtest_capital(
        plan,
        initial_cash_jpy=initial_cash_jpy,
        max_position_pct=max_position_pct,
        min_cash_reserve_pct=min_cash_reserve_pct,
    )
    stale = list_strategies_needing_capital_refresh(strategy_ids, record)
    click.echo("有効な資金条件（この run で使われる値）:")
    click.echo(json.dumps(record, ensure_ascii=False, indent=2))
    click.echo(f"\nbacktest_capital 未記録 or 不一致の完了戦略: {len(stale)} / {len(strategy_ids)}")
    click.echo("再BT: experiments run --refresh-capital （必要なら --initial-cash-jpy 等）")


def _entry_rule_options(fn):
    from signalforge.lab.portfolio_sim import DEFAULT_ENTRY_RULES, ENTRY_PRIORITIES, REGIME_FILTERS

    fn = click.option(
        "--legacy-rules",
        is_flag=True,
        help="旧ルール（流動性タグ順・出来高/ブレッドス条件なし）で比較",
    )(fn)
    fn = click.option(
        "--regime-filter",
        default=DEFAULT_ENTRY_RULES["regime_filter"],
        show_default=True,
        type=click.Choice(list(REGIME_FILTERS)),
    )(fn)
    fn = click.option(
        "--min-breadth-rank",
        default=DEFAULT_ENTRY_RULES["min_breadth_rank"],
        show_default=True,
        type=float,
        help="当日シグナル数が過去1年の何割以上の日だけ新規（0=無効）",
    )(fn)
    fn = click.option(
        "--min-turnover-jpy",
        default=DEFAULT_ENTRY_RULES["min_turnover_jpy"],
        show_default=True,
        type=float,
        help="直近20日平均売買代金の下限（円, 0=無効）",
    )(fn)
    fn = click.option(
        "--entry-priority",
        default=DEFAULT_ENTRY_RULES["entry_priority"],
        show_default=True,
        type=click.Choice(list(ENTRY_PRIORITIES)),
    )(fn)
    return fn


def _entry_rules_from_cli(
    entry_priority: str,
    min_turnover_jpy: float,
    min_breadth_rank: float,
    regime_filter: str,
    legacy_rules: bool,
) -> dict[str, Any]:
    from signalforge.lab.portfolio_sim import LEGACY_ENTRY_RULES

    if legacy_rules:
        return dict(LEGACY_ENTRY_RULES)
    return {
        "entry_priority": entry_priority,
        "min_turnover_jpy": min_turnover_jpy,
        "min_breadth_rank": min_breadth_rank,
        "regime_filter": regime_filter,
    }


@experiments.command("portfolio")
@click.argument("strategy_id")
@click.option("--initial-cash-jpy", default=None, type=float)
@click.option("--max-positions", default=5, show_default=True, type=int)
@click.option("--position-pct", default=0.2, show_default=True, type=float)
@_entry_rule_options
def experiments_portfolio_cmd(
    strategy_id: str,
    initial_cash_jpy: float | None,
    max_positions: int,
    position_pct: float,
    entry_priority: str,
    min_turnover_jpy: float,
    min_breadth_rank: float,
    regime_filter: str,
    legacy_rules: bool,
) -> None:
    """1口座・分散制約で TSE 実験トレードを再シミュレーション（同時保有上限・入口ルール）。"""
    from signalforge.portfolio.diversified import simulate_from_experiment_strategy

    rules = _entry_rules_from_cli(entry_priority, min_turnover_jpy, min_breadth_rank, regime_filter, legacy_rules)
    try:
        out = simulate_from_experiment_strategy(
            strategy_id,
            initial_cash_jpy=initial_cash_jpy,
            max_positions=max_positions,
            position_pct=position_pct,
            entry_rules=rules,
        )
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"入口ルール: {rules}")

    click.echo(f"戦略: {strategy_id}")
    click.echo(
        f"銘柄: {out['n_tickers_with_trades']} / {out['n_tickers']} "
        f"(系列あり {out['n_tickers_with_series']})"
    )
    click.echo(f"プール内トレード: {out['n_trades_in_pool']}")
    click.echo(
        f"口座 ¥{out['initial_capital']:,.0f} · 同時最大 {out['max_positions']} · "
        f"1回 {out['position_pct'] * 100:.0f}%"
    )
    click.echo(f"採用トレード: {out['accepted_trades']} · スキップ（枠/重複）: {out['skipped_overlap']}")
    click.echo(f"最終評価額: ¥{out['final_equity']:,.0f} · 総リターン: {out['total_return_pct']:+.2f}%")
    click.echo(f"最大DD: {out.get('max_drawdown_pct', 0):.1f}% · 勝率: {out.get('win_rate_pct') or 0:.1f}%")


@experiments.command("portfolio-all")
@click.option("--initial-cash-jpy", default=None, type=float)
@click.option("--max-positions", default=5, show_default=True, type=int)
@click.option("--position-pct", default=0.2, show_default=True, type=float)
@_entry_rule_options
def experiments_portfolio_all_cmd(
    initial_cash_jpy: float | None,
    max_positions: int,
    position_pct: float,
    entry_priority: str,
    min_turnover_jpy: float,
    min_breadth_rank: float,
    regime_filter: str,
    legacy_rules: bool,
) -> None:
    """完了 TSE 実験戦略の 1口座シム結果を portfolio_returns.json にキャッシュ。"""
    from signalforge.experiments.portfolio_returns import build_portfolio_returns_cache
    from signalforge.experiments.scan import scan_campaign_progress

    scan = scan_campaign_progress(fast=True)
    sids = [r["strategy_id"] for r in scan.get("complete") or []]
    if not sids:
        raise click.ClickException("完了戦略がありません。")
    doc = build_portfolio_returns_cache(
        sids,
        initial_cash_jpy=initial_cash_jpy,
        max_positions=max_positions,
        position_pct=position_pct,
        entry_rules=_entry_rules_from_cli(
            entry_priority, min_turnover_jpy, min_breadth_rank, regime_filter, legacy_rules
        ),
    )
    n_ok = sum(1 for v in doc.get("strategies", {}).values() if "total_return_pct" in v)
    click.echo(f"キャッシュ: {doc['params']}")
    click.echo(f"書き込み: {n_ok} / {len(sids)} 戦略")


@experiments.command("portfolio-compare")
@click.argument("strategy_ids", nargs=-1, required=True)
@click.option(
    "--priorities",
    default="sector_random,sector_liquidity,sector_turnover",
    show_default=True,
    help="カンマ区切り entry_priority",
)
@click.option("--regimes", default="none,ma200", show_default=True, help="カンマ区切り regime_filter")
@click.option("--turnovers", default="0,5e8", show_default=True, help="カンマ区切り min_turnover_jpy")
@click.option("--breadths", default="0,0.8", show_default=True, help="カンマ区切り min_breadth_rank")
@click.option("--seeds", default=10, show_default=True, type=int, help="同点ランダム順の試行回数（中央値・下位10%）")
@click.option("--oos-start", default="2024-01-01", show_default=True)
def experiments_portfolio_compare_cmd(
    strategy_ids: tuple[str, ...],
    priorities: str,
    regimes: str,
    turnovers: str,
    breadths: str,
    seeds: int,
    oos_start: str,
) -> None:
    """入口ルールの組み合わせを 1口座シムで比較（前半/後半 2024- 分割、ランダム同点順の分布）。"""
    from signalforge.experiments.portfolio_compare import compare_portfolio_variants

    def _row(r: dict[str, Any]) -> None:
        click.echo(
            f"{r['strategy_id']:28s} {r['entry_priority']:16s} {r['regime_filter']:11s} "
            f"tv≥{r['min_turnover_jpy']:.0e} br≥{r['min_breadth_rank']:.1f} | "
            f"中央値 {r['total_return_pct']:+7.1f}% (下位10% {r['p10_return_pct']:+7.1f}%) "
            f"前半 {r['is_return_pct']:+7.1f}% 後半 {r['oos_return_pct']:+7.1f}% "
            f"DD {r['max_drawdown_pct']:6.1f}% n={r['accepted_trades']:.0f}"
        )

    doc = compare_portfolio_variants(
        list(strategy_ids),
        entry_priorities=[s.strip() for s in priorities.split(",") if s.strip()],
        regime_filters=[s.strip() for s in regimes.split(",") if s.strip()],
        min_turnovers=[float(s) for s in turnovers.split(",") if s.strip()],
        min_breadths=[float(s) for s in breadths.split(",") if s.strip()],
        seeds=seeds,
        oos_start=oos_start,
        progress_cb=_row,
    )
    click.echo(f"書き込み: {len(doc['rows'])} 行 → data/reports/experiments/portfolio_compare.json")


@experiments.command("exit-sweep")
@click.argument("strategy_ids", nargs=-1, required=True)
@click.option("--variants", default="", help="カンマ区切り（空=全バリアント）")
@click.option("--min-median-turnover-jpy", default=3e8, show_default=True, type=float)
@click.option("--workers", default=8, show_default=True, type=int)
@click.option("--seeds", default=10, show_default=True, type=int)
def experiments_exit_sweep_cmd(
    strategy_ids: tuple[str, ...],
    variants: str,
    min_median_turnover_jpy: float,
    workers: int,
    seeds: int,
) -> None:
    """決済ルール（利確/損切り ATR 倍率・最大保有）を流動銘柄で再BTし、1口座ルールで比較。"""
    from signalforge.experiments.exit_sweep import EXIT_VARIANTS, liquid_tse_tickers, run_exit_sweep

    names = [v.strip() for v in variants.split(",") if v.strip()] or list(EXIT_VARIANTS)
    unknown = [v for v in names if v not in EXIT_VARIANTS]
    if unknown:
        raise click.ClickException(f"未知のバリアント: {unknown}（候補: {list(EXIT_VARIANTS)}）")
    universe = liquid_tse_tickers(min_median_turnover_jpy)
    click.echo(f"対象銘柄: {len(universe)}（中央値売買代金 ≥ ¥{min_median_turnover_jpy:,.0f}）")

    def _row(r: dict[str, Any]) -> None:
        click.echo(
            f"{r['strategy_id']:28s} {r['variant']:22s} 平均 {r['mean_pnl_pct']:+.2f}% | "
            f"1口座 {r['total_return_pct']:+7.1f}% 前半 {r['is_return_pct'] or 0:+7.1f}% "
            f"後半 {r['oos_return_pct'] or 0:+7.1f}% DD {r['max_drawdown_pct']:6.1f}% | "
            f"ランダム中央値 {r['random_median_return_pct']:+7.1f}% 下位10% {r['random_p10_return_pct']:+7.1f}%",
            nl=True,
        )

    run_exit_sweep(
        list(strategy_ids),
        variants=names,
        tickers=universe,
        workers=workers,
        seeds=seeds,
        progress_cb=_row,
    )
    click.echo("書き込み: data/reports/experiments/exit_sweep.json")


@experiments.command("schedule")
def experiments_schedule_cmd() -> None:
    """Show execution schedule (config/experiments/schedule.yaml)."""
    from signalforge.experiments.runner import default_parallel_workers
    from signalforge.experiments.schedule import ExecutionBudget, load_schedule

    doc = load_schedule()
    b = ExecutionBudget.from_config(doc)
    click.echo("execution (schedule.yaml):")
    click.echo(json.dumps(b.to_manifest_fragment(), ensure_ascii=False, indent=2))
    click.echo(f"effective parallel_workers: {default_parallel_workers()}")


@experiments.command("run")
@click.option("--strategy-limit", default=0, type=int, help="Cap strategies (0=all, 省略なし)")
@click.option("--ticker-limit", default=0, type=int, help="Cap tickers (0=全TSE内国株式)")
@click.option("--workers", default=0, type=int, help="Parallel workers (0=schedule/auto)")
@click.option("--max-minutes", default=-1.0, type=float, help="Wall clock limit (-1=schedule.yaml)")
@click.option("--ignore-schedule", is_flag=True, help="Run outside active_hours window")
@click.option("--no-resume", is_flag=True, help="Ignore checkpoints (未完了戦略は銘柄単位で再開)")
@click.option(
    "--refresh-metrics",
    is_flag=True,
    help="完了済み戦略のうち期待値・最大DD が未保存のものだけ全銘柄を再BT",
)
@click.option(
    "--refresh-series",
    is_flag=True,
    help="期間スライス用に trades_compact / equity_daily が無い銘柄だけ再BT",
)
@click.option(
    "--refresh-capital",
    is_flag=True,
    help="完了済みのうち backtest_capital が現設定と違う戦略を全銘柄再BT",
)
@click.option("--initial-cash-jpy", default=None, type=float, help="実験BTの口座サイズ（円）")
@click.option("--max-position-pct", default=None, type=float, help="1エントリー上限（口座比、例 0.35）")
@click.option(
    "--min-cash-reserve-pct",
    default=None,
    type=float,
    help="常に残す現金比率（例 0.1）",
)
@click.option("--aggregate-only", is_flag=True, help="Rebuild matrices from saved strategy JSON")
@click.option("--only", multiple=True, help="この戦略IDだけ実行する。再計算するときは --no-resume を付ける")
def experiments_run(
    strategy_limit: int,
    ticker_limit: int,
    workers: int,
    max_minutes: float,
    ignore_schedule: bool,
    no_resume: bool,
    refresh_metrics: bool,
    refresh_series: bool,
    refresh_capital: bool,
    initial_cash_jpy: float | None,
    max_position_pct: float | None,
    min_cash_reserve_pct: float | None,
    aggregate_only: bool,
    only: tuple[str, ...],
) -> None:
    """Run JPX universe experiment: 全銘柄×全戦略、並列+再開。schedule.yaml で時間調整可。"""
    from signalforge.experiments.runner import (
        build_experiment_summaries,
        default_parallel_workers,
        load_plan,
        run_experiment_campaign,
    )
    from signalforge.experiments.schedule import ExecutionBudget
    from signalforge.universe.tse_listing import list_tse_tickers

    plan = load_plan()
    cost = (plan.get("meta") or {}).get("cost_model", "japan")
    strategy_ids = _parse_strategy_ids(plan.get("strategies", "catalog:all"), None, strategy_limit)
    if only:
        wanted = set(only)
        unknown = wanted.difference(strategy_ids)
        if unknown:
            raise click.ClickException(f"未知の戦略ID: {', '.join(sorted(unknown))}")
        strategy_ids = [sid for sid in strategy_ids if sid in wanted]
    cat_by_id = {s["id"]: s for s in load_web_catalog().get("strategies", [])}

    if aggregate_only:
        n = ticker_limit or len(list_tse_tickers())
        from signalforge.experiments.intraday_campaign import PRICE_INTRADAY_STRATEGIES
        from signalforge.experiments.runner import refresh_completed_strategy_aggregates

        if not only:
            skip = set(PRICE_INTRADAY_STRATEGIES)
            strategy_ids = [sid for sid in strategy_ids if sid not in skip]
        refreshed = refresh_completed_strategy_aggregates(strategy_ids)
        build_experiment_summaries(strategy_ids, tickers_count=n)
        click.echo(
            f"Aggregates refreshed → data/reports/experiments/ "
            f"（{refreshed} 戦略の universe を銘柄 sidecar から再集計）"
        )
        return

    overrides: dict = {}
    if max_minutes >= 0:
        overrides["max_minutes_per_run"] = max_minutes
    if workers > 0:
        overrides["parallel_workers"] = workers
    budget = ExecutionBudget.from_config(overrides=overrides)
    if workers <= 0 and budget.parallel_workers <= 0:
        budget.parallel_workers = default_parallel_workers()

    ok, msg = budget.check_may_run(ignore_window=ignore_schedule)
    if not ok:
        raise click.ClickException(msg)

    n_tickers = ticker_limit or len(list_tse_tickers())
    if ticker_limit == 0 and budget.max_tickers_per_strategy > 0:
        n_tickers = budget.max_tickers_per_strategy

    current_sid: list[str] = [""]

    def _prog(i: int, total: int, sid: str) -> None:
        current_sid[0] = sid.replace(" (skip)", "").replace(" (完了済み)", "")
        click.echo(f"  [{i}/{total}] {sid}")

    def _tprog(i: int, n: int, sym: str) -> None:
        click.echo(f"      … {current_sid[0]} tickers {i}/{n} ({sym})")

    from signalforge.experiments.runner import (
        list_strategies_needing_capital_refresh,
        list_strategies_needing_metric_refresh,
        list_strategies_needing_series_refresh,
        resolve_campaign_backtest_capital,
    )

    capital_record, _ = resolve_campaign_backtest_capital(
        plan,
        initial_cash_jpy=initial_cash_jpy,
        max_position_pct=max_position_pct,
        min_cash_reserve_pct=min_cash_reserve_pct,
    )
    click.echo(f"資金条件: {json.dumps(capital_record, ensure_ascii=False)}")

    need_metrics: list[str] = []
    need_capital: list[str] = []
    if refresh_metrics:
        need_metrics = list_strategies_needing_metric_refresh(strategy_ids)
        click.echo(f"指標更新が必要な完了戦略: {len(need_metrics)} / {len(strategy_ids)}")
    need_series: list[str] = []
    if refresh_series:
        need_series = list_strategies_needing_series_refresh(strategy_ids)
        click.echo(f"系列データ追記が必要な完了戦略: {len(need_series)} / {len(strategy_ids)}")
    if refresh_capital:
        need_capital = list_strategies_needing_capital_refresh(strategy_ids, capital_record)
        click.echo(f"資金条件が古い完了戦略: {len(need_capital)} / {len(strategy_ids)}")

    if (refresh_metrics or refresh_series or refresh_capital) and not need_metrics and not need_series and not need_capital:
        click.echo("再BT不要。aggregate のみ実行します。")
        ctx = click.get_current_context()
        ctx.invoke(
            experiments_run,
            strategy_limit=strategy_limit,
            ticker_limit=ticker_limit,
            workers=workers,
            max_minutes=max_minutes,
            ignore_schedule=ignore_schedule,
            no_resume=no_resume,
            refresh_metrics=False,
            refresh_series=False,
            refresh_capital=False,
            initial_cash_jpy=initial_cash_jpy,
            max_position_pct=max_position_pct,
            min_cash_reserve_pct=min_cash_reserve_pct,
            aggregate_only=True,
        )
        return

    extras = []
    if refresh_metrics:
        extras.append("refresh-metrics")
    if refresh_series:
        extras.append("refresh-series")
    if refresh_capital:
        extras.append("refresh-capital")
    click.echo(
        f"\n=== TSE experiment: {len(strategy_ids)} strategies × {n_tickers} tickers "
        f"(workers={budget.parallel_workers}"
        f"{', ' + ', '.join(extras) if extras else ''}) ===\n"
    )
    man = run_experiment_campaign(
        strategy_ids,
        ticker_limit=ticker_limit,
        cost_model=cost,
        catalog_by_id=cat_by_id,
        resume=not no_resume,
        budget=budget,
        progress_cb=_prog,
        ticker_progress_cb=_tprog,
        refresh_metrics=refresh_metrics,
        refresh_series=refresh_series,
        refresh_capital=refresh_capital,
        initial_cash_jpy=initial_cash_jpy,
        max_position_pct=max_position_pct,
        min_cash_reserve_pct=min_cash_reserve_pct,
        plan=plan,
    )
    click.echo(
        f"\n✓ new={man['completed']} 完了済skip={man['skipped_complete']} "
        f"指標再BT={man.get('refreshed_metrics', 0)} "
        f"資金再BT={man.get('refreshed_capital', 0)} "
        f"fail={man['failed']} early_stop={man.get('stopped_early', 0)}"
    )
    click.echo(f"  manifest: {experiments_dir() / 'manifest.json'}")


@experiments.command("compact")
@click.option("--split-tickers/--inline-tickers", default=True, help="銘柄行を .tickers.json に分離")
@click.option("--strategy", "only_strategy", default=None, help="1 戦略だけ処理")
def experiments_compact_cmd(split_tickers: bool, only_strategy: str | None) -> None:
    """既存 strategy JSON を compact 化（nested metrics 削除・sidecar 分離）。"""
    from signalforge.experiments.migrate_checkpoint import migrate_oversized_checkpoints
    from signalforge.experiments.storage import compact_strategy_file

    ck = migrate_oversized_checkpoints()
    if ck:
        click.echo(f"checkpoint 分離: {', '.join(ck)}")

    strat_dir = experiments_dir() / "strategies"
    if not strat_dir.is_dir():
        raise click.ClickException("experiments/strategies がありません")
    paths = sorted(strat_dir.glob("*.json"))
    paths = [p for p in paths if not p.name.endswith(".tickers.json") and not p.name.endswith(".checkpoint.json")]
    if only_strategy:
        paths = [p for p in paths if p.stem == only_strategy]
    if not paths:
        click.echo("対象ファイルなし")
        return
    total_saved = 0
    for path in paths:
        n, saved = compact_strategy_file(path, split_tickers=split_tickers)
        total_saved += saved
        click.echo(f"  {path.name}: {n} tickers, ~{saved // 1024} KB 削減")
    click.echo(f"✓ {len(paths)} ファイル処理 · 合計 ~{total_saved // (1024 * 1024)} MB 削減")


@experiments.command("aggregate")
def experiments_aggregate_cmd() -> None:
    """Rebuild segment/sector matrices and catalog_backtests from strategy JSON."""
    ctx = click.get_current_context()
    ctx.invoke(
        experiments_run,
        strategy_limit=0,
        ticker_limit=0,
        workers=0,
        max_minutes=-1.0,
        ignore_schedule=True,
        no_resume=False,
        aggregate_only=True,
    )


def experiments_dir() -> Path:
    from signalforge.experiments.runner import experiments_dir as _d

    return _d()


@main.group()
def results() -> None:
    """Precomputed strategy reports (catalog / cohort / lab) for dashboard & hub."""


@results.command("status")
def results_status() -> None:
    """Show ages of report JSON files."""
    from datetime import datetime

    rep = data_dir() / "reports"
    names = [
        "catalog_backtests.json",
        "compare_matrix.json",
        "lab_matrix.json",
        "hub/index.html",
        "hub/manifest.json",
    ]
    click.echo("事前バックテスト結果:")
    for name in names:
        p = rep / name
        if p.is_file():
            ts = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            click.echo(f"  ✓ {name}  ({ts})")
        else:
            click.echo(f"  — {name}  (未生成)")
    click.echo("\n生成: uv run signalforge results build")
    click.echo("閲覧: uv run signalforge dashboard start  /  uv run signalforge hub open")


@results.command("sync-catalog")
def results_sync_catalog() -> None:
    """Rebuild catalog_backtests.json from compare_matrix (multi-ticker, no re-run)."""
    cmp_path = data_dir() / "reports" / "compare_matrix.json"
    if not cmp_path.exists():
        raise click.ClickException("compare_matrix.json がありません。先に results build を実行してください。")
    cmp_result = json.loads(cmp_path.read_text(encoding="utf-8"))
    from signalforge.compare.runner import catalog_rows_from_compare_matrix

    rows = catalog_rows_from_compare_matrix(cmp_result)
    n_pool = max((r.get("n_tickers") or 0) for r in rows) if rows else 0
    out = data_dir() / "reports" / "catalog_backtests.json"
    out.write_text(
        json.dumps(
            {
                "meta": {
                    "evaluation": "multi_ticker_median",
                    "n_tickers": n_pool,
                    "source": "compare_matrix_pooled",
                },
                "results": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    click.echo(f"✓ {out} — {len(rows)} 戦略 · 最大 {n_pool} 銘柄プール")


@results.command("build")
@click.option("--quick", is_flag=True, help="Catalog + lab only; cohort matrix skipped")
@click.option("--fetch-data", is_flag=True, help="Refresh OHLCV for meta tickers first")
@click.option("--ticker-limit", default=0, type=int, help="Cap tickers per cohort/lab (0=all)")
def results_build(quick: bool, fetch_data: bool, ticker_limit: int) -> None:
    """Run hub build (all strategies pre-backtested). Default: use cached OHLCV."""
    ctx = click.get_current_context()
    ctx.invoke(
        hub_build,
        fetch_data=fetch_data,
        ticker_limit=ticker_limit,
        skip_catalog=False,
        skip_cohort=quick,
        skip_lab=False,
    )


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

    import os

    jq = (os.getenv("JQUANTS_API_KEY") or "").strip()
    if jq:
        click.echo(f"J-Quants API key: set ({len(jq)} chars) — uv run signalforge alt-data jquants-test")
    else:
        click.echo(
            "J-Quants API key: 未設定 — 信用残戦略用: "
            "https://jpx-jquants.com/ → export JQUANTS_API_KEY=…"
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
@click.option("--guides-only", is_flag=True, help="戦略解説 HTML のみ（Paper/BT 省略）")
def dashboard_export(
    output: str,
    style: str | None,
    strategy: str | None,
    refresh: bool,
    guides_only: bool,
) -> None:
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

    path = export_full_site(out, refresh=refresh, guides_only=guides_only)
    if guides_only:
        click.echo(f"✅ 戦略解説のみ: {path.resolve()}")
    else:
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
    from signalforge.paper.portfolio import PaperPortfolio, format_paper_amount
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
    click.echo(f"   初期資金: {format_paper_amount(p, p.initial_cash)}")
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
    from signalforge.paper.portfolio import format_paper_amount
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
        click.echo(f"現在評価額: {format_paper_amount(p, out['equity'])}")
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
    click.echo(f"評価額: {format_paper_amount(p, out['equity'])}")
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
    from signalforge.paper.portfolio import PaperPortfolio, format_paper_amount

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
    click.echo(f"現金: {format_paper_amount(p, p.cash)}")
    click.echo(f"最新評価額: {format_paper_amount(p, eq)}")
    click.echo(f"クローズドトレード: {len(p.closed_trades)}")
    if p.position:
        click.echo(f"建玉: {p.position.get('side')} @ {p.position.get('entry_price')} ({p.position.get('entry_time')})")


@paper.command("diversified-init")
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
@click.option("--strategy", required=True)
@click.option("--cohort", default="prime", show_default=True)
@click.option("--ticker-limit", default=0, type=int, help="0=コホート全件")
@click.option("--cost-model", default="japan", type=COST_MODEL_CHOICE)
@click.option("--initial-cash-jpy", default=None, type=float)
@click.option("--max-positions", default=5, show_default=True, type=int)
@click.option("--position-pct", default=0.2, show_default=True, type=float)
@click.option("--workers", default=8, show_default=True, type=int)
def paper_diversified_init(
    style: str,
    strategy: str,
    cohort: str,
    ticker_limit: int,
    cost_model: str,
    initial_cash_jpy: float | None,
    max_positions: int,
    position_pct: float,
    workers: int,
) -> None:
    """1口座・ユニバース横断のフォワードペーパー（最終足以降のエントリのみ）。"""
    from signalforge.paper.diversified import DiversifiedPaperBook, init_diversified_paper

    if DiversifiedPaperBook.load(style, strategy):
        raise click.ClickException(
            f"既に diversified 口座があります。`paper diversified-reset --style {style} --strategy {strategy}`"
        )
    book = init_diversified_paper(
        style,
        strategy,
        cohort=cohort,
        ticker_limit=ticker_limit,
        cost_model=cost_model,
        initial_cash_jpy=initial_cash_jpy,
        max_positions=max_positions,
        position_pct=position_pct,
        workers=workers,
        refresh=True,
    )
    sim = book.last_sim or {}
    click.echo(f"✅ Diversified paper: {style} / {strategy} · {book.universe_size} 銘柄 ({cohort})")
    click.echo(f"   エントリ開始: {book.entry_cutoff} より後")
    click.echo(f"   口座 ¥{book.initial_capital:,.0f} · 同時 {book.max_positions} · {book.position_pct * 100:.0f}%/回")
    click.echo(f"   評価額: ¥{sim.get('final_equity', book.initial_capital):,.0f}")
    click.echo(f"   保存: {book.save()}")


@paper.command("diversified-run")
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
@click.option("--strategy", required=True)
@click.option("--refresh/--no-refresh", default=True)
@click.option("--workers", default=None, type=int, help="未指定なら口座保存値")
def paper_diversified_run(style: str, strategy: str, refresh: bool, workers: int | None) -> None:
    """ユニバースを更新し、分散ルールでフォワード成績を再計算。"""
    from signalforge.paper.diversified import DiversifiedPaperBook, run_diversified_paper

    book = DiversifiedPaperBook.load(style, strategy)
    if not book:
        raise click.ClickException("口座がありません。`paper diversified-init` を実行してください。")
    out = run_diversified_paper(book, refresh=refresh, workers=workers)
    sim = out["simulation"]
    click.echo(f"=== Diversified paper: {style} / {strategy} ===")
    click.echo(f"フォワード候補トレード: {out['n_trades_forward']}")
    click.echo(f"採用: {sim.get('accepted_trades', 0)} · スキップ: {sim.get('skipped_overlap', 0)}")
    click.echo(f"評価額: ¥{sim.get('final_equity', book.initial_capital):,.0f} · リターン {sim.get('total_return_pct', 0):+.2f}%")


@paper.command("diversified-init-all")
@click.option("--cohort", default="prime_liquid", show_default=True)
@click.option("--ticker-limit", default=0, type=int)
@click.option("--workers", default=8, show_default=True, type=int)
@click.option("--skip-existing/--force", default=True, help="既存口座はスキップ")
def paper_diversified_init_all(
    cohort: str,
    ticker_limit: int,
    workers: int,
    skip_existing: bool,
) -> None:
    """DIVERSIFIED_PAPER_SIMULATIONS の口座をまとめて init。"""
    from signalforge.paper.diversified import DiversifiedPaperBook, init_diversified_paper
    from signalforge.paper.matrix import DIVERSIFIED_PAPER_SIMULATIONS

    for spec in DIVERSIFIED_PAPER_SIMULATIONS:
        style, strategy, spec_cohort = spec.style, spec.strategy, spec.cohort
        use_cohort = cohort if cohort != "prime_liquid" else spec_cohort
        if skip_existing and DiversifiedPaperBook.load(style, strategy):
            click.echo(f"⏭  {strategy}（既存）")
            continue
        if not skip_existing:
            from signalforge.paper.diversified import diversified_book_path

            diversified_book_path(style, strategy).unlink(missing_ok=True)
        click.echo(f"→ init {strategy} ({use_cohort}) …")
        init_diversified_paper(
            style,
            strategy,
            cohort=use_cohort,
            ticker_limit=ticker_limit,
            workers=workers,
            refresh=True,
        )
        click.echo(f"✓ {strategy}")


@paper.command("diversified-run-all")
@click.option("--refresh/--no-refresh", default=True)
@click.option("--workers", default=8, show_default=True, type=int)
def paper_diversified_run_all(refresh: bool, workers: int) -> None:
    """Advance all diversified paper accounts (TSE フォワード検証用ペア)."""
    from signalforge.paper.diversified import DiversifiedPaperBook, run_diversified_paper
    from signalforge.paper.matrix import DIVERSIFIED_PAPER_SIMULATIONS

    for spec in DIVERSIFIED_PAPER_SIMULATIONS:
        style, strategy = spec.style, spec.strategy
        book = DiversifiedPaperBook.load(style, strategy)
        if not book:
            click.echo(f"⏭  未 init: {strategy}")
            continue
        try:
            out = run_diversified_paper(book, refresh=refresh, workers=workers)
            sim = out["simulation"]
            click.echo(
                f"✓ {strategy}: フォワード {out['n_trades_forward']} · "
                f"¥{sim.get('final_equity', 0):,.0f} ({sim.get('total_return_pct', 0):+.2f}%)"
            )
        except Exception as exc:
            click.echo(f"✗ {strategy}: {exc}")


@paper.command("diversified-status")
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
@click.option("--strategy", required=True)
def paper_diversified_status(style: str, strategy: str) -> None:
    from signalforge.paper.diversified import DiversifiedPaperBook

    book = DiversifiedPaperBook.load(style, strategy)
    if not book:
        raise click.ClickException("口座がありません。")
    sim = book.last_sim or {}
    click.echo(f"Diversified: {style} / {strategy}")
    click.echo(f"コホート: {book.cohort} · 銘柄数: {book.universe_size}")
    click.echo(f"開始: {book.started_at} · エントリ cutoff: {book.entry_cutoff}")
    click.echo(f"最終実行: {book.last_run_at}")
    click.echo(
        f"¥{book.initial_capital:,.0f} → ¥{sim.get('final_equity', book.initial_capital):,.0f} "
        f"({sim.get('total_return_pct', 0):+.2f}%)"
    )


@paper.command("diversified-reset")
@click.option("--style", default="swing", type=click.Choice(STYLE_CHOICES))
@click.option("--strategy", required=True)
@click.confirmation_option(prompt="Diversified paper 口座を削除しますか？")
def paper_diversified_reset(style: str, strategy: str) -> None:
    from signalforge.paper.diversified import diversified_book_path

    path = diversified_book_path(style, strategy)
    if path.exists():
        path.unlink()
    click.echo("Diversified paper をリセットしました。")


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
