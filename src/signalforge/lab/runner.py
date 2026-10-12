from __future__ import annotations

import time
from typing import Any

import pandas as pd

from signalforge.config import load_style_config, market_context
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.data.window import resolve_backtest_dates, slice_for_indicators, trim_to_backtest_window
from signalforge.indicators.engine import IndicatorEngine
from signalforge.lab.cache import fingerprint, load_study, merge_ticker_results, save_study
from signalforge.lab.dsl_strategy import DslEntryStrategy
from signalforge.lab.execution import simulate_with_fills
from signalforge.lab.izanami_report import build_overview_report
from signalforge.lab.palette import resolve_palette_rule
from signalforge.lab.portfolio_sim import simulate_diversified_portfolio
from signalforge.lab.report import aggregate_ticker_results
from signalforge.lab.signals_timeline import daily_signal_bars
from signalforge.pipeline import resolve_data_source
from signalforge.strategies.registry import get_strategy
from signalforge.universe.filters import load_equity_meta


def _prepare_df(ticker: str, style: str, cfg_override: dict | None) -> tuple[pd.DataFrame, dict]:
    cfg = load_style_config(style)
    if cfg_override:
        for k, v in cfg_override.items():
            if k == "backtest" and isinstance(v, dict):
                cfg["backtest"] = {**cfg.get("backtest", {}), **v}
            else:
                cfg[k] = v
    mc = market_context(cfg)
    timeframe = cfg.get("timeframe", "1d")
    fetcher = MarketDataFetcher(data_source=resolve_data_source(style, cfg))
    cache = ParquetCache()
    df = cache.load_or_fetch(ticker, timeframe, fetcher, refresh=False)
    bt_start, bt_end = resolve_backtest_dates(cfg)
    df = slice_for_indicators(df, bt_start)
    tz = mc.get("timezone", "Asia/Tokyo")
    intraday = style == "daytrade"
    df = IndicatorEngine(timezone=tz).compute(df, intraday=intraday)
    df = trim_to_backtest_window(df, bt_start, bt_end)
    calendar_days = max((df.index[-1] - df.index[0]).days, 1) if len(df) > 1 else 1
    return df, {"cfg": cfg, "calendar_days": calendar_days, "bt_start": bt_start, "bt_end": bt_end}


def _strategy_for_rule(spec: dict[str, Any], cfg: dict[str, Any]):
    if spec.get("entry"):
        return DslEntryStrategy({**cfg, "_entry_spec": spec["entry"], "_catalog_id": spec.get("id", "dsl")})
    return get_strategy(spec["strategy"], cfg)


def _serialize_trades(trades: pd.DataFrame, ticker: str) -> list[dict]:
    trade_records = trades.to_dict(orient="records")
    for tr in trade_records:
        tr["ticker"] = ticker
        for k in ("signal_time", "entry_time", "exit_time"):
            if k in tr:
                tr[k] = str(tr[k])
    return trade_records


def run_rule_study_on_ticker(
    rule_id: str,
    ticker: str,
    *,
    cfg_override: dict | None = None,
    execution: dict | None = None,
) -> dict[str, Any]:
    spec = resolve_palette_rule(rule_id)
    strategy_id = spec.get("strategy") or rule_id
    style = spec.get("style") or spec.get("defaults", {}).get("style", "swing")
    exit_cfg = {**spec.get("defaults", {}).get("exit", {}), **spec.get("exit", {})}
    exec_cfg = execution or spec.get("execution") or {}

    try:
        t0 = time.perf_counter()
        df, ctx = _prepare_df(ticker, style, cfg_override)
        strat = _strategy_for_rule(spec, ctx["cfg"])
        signals = strat.generate_signals(df)
        trades, fill_stats = simulate_with_fills(
            df,
            signals,
            max_hold=int(exit_cfg.get("max_hold_bars", 15)),
            atr_tp=float(exit_cfg.get("atr_tp_multiple", 3.0)),
            atr_sl=float(exit_cfg.get("atr_sl_multiple", 1.5)),
            use_limit_entry=bool(exec_cfg.get("limit_entry", False)),
            limit_entry_offset_pct=float(exec_cfg.get("limit_offset_pct", 0)),
        )
        if not trades.empty:
            trades = trades.copy()
            trades["ticker"] = ticker
        elapsed = time.perf_counter() - t0
        trade_records = _serialize_trades(trades, ticker)
        last_signal = None
        if len(signals) and int(signals.iloc[-1]) > 0:
            last_signal = {
                "ticker": ticker,
                "time": str(df.index[-1]),
                "close": float(df.iloc[-1]["close"]),
                "rsi_14": float(df.iloc[-1].get("rsi_14", 0)),
            }
        return {
            "rule_id": rule_id,
            "strategy": strategy_id,
            "ticker": ticker,
            "style": style,
            "trades": trade_records,
            "fill_stats": fill_stats,
            "elapsed_sec": elapsed,
            "calendar_days": ctx["calendar_days"],
            "last_signal": last_signal,
            "error": None,
        }
    except Exception as exc:
        return {"rule_id": rule_id, "ticker": ticker, "error": str(exc), "trades": [], "fill_stats": {}}


def run_rule_study_universe(
    rule_id: str,
    tickers: list[str],
    *,
    cfg_override: dict | None = None,
    use_cache: bool = False,
    save_cache: bool = False,
    incremental_tickers: list[str] | None = None,
) -> dict[str, Any]:
    spec = resolve_palette_rule(rule_id)
    fp = fingerprint(rule_id, tickers, cfg_override or {})
    cached = load_study(fp) if (use_cache or save_cache) else None
    if use_cache and cached and not incremental_tickers:
        return cached

    run_list = incremental_tickers if incremental_tickers else tickers
    if cached and incremental_tickers:
        per_ticker = [run_rule_study_on_ticker(rule_id, sym, cfg_override=cfg_override) for sym in run_list]
        merged = merge_ticker_results(cached, per_ticker)
        per_ticker = merged["by_ticker"]
    else:
        per_ticker = [run_rule_study_on_ticker(rule_id, sym, cfg_override=cfg_override) for sym in run_list]
        if cached and use_cache:
            per_ticker = merge_ticker_results(cached, per_ticker)["by_ticker"]

    all_frames = []
    total_fill: dict[str, int] = {}
    for r in per_ticker:
        if r.get("error") or not r.get("trades"):
            continue
        fs = r.get("fill_stats") or {}
        for k, v in fs.items():
            total_fill[k] = total_fill.get(k, 0) + int(v)
        all_frames.append(pd.DataFrame(r["trades"]))

    pool = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()
    meta = load_equity_meta().get("tickers", {})
    overview = build_overview_report(
        pool,
        rule_name=spec.get("name", rule_id),
        fill_stats=total_fill,
        ticker_meta=meta,
        elapsed_sec=sum(float(r.get("elapsed_sec") or 0) for r in per_ticker),
    )
    portfolio = simulate_diversified_portfolio(pool)
    last_signals = [r["last_signal"] for r in per_ticker if r.get("last_signal")]

    result = {
        "rule_id": rule_id,
        "rule_name": spec.get("name", rule_id),
        "universe_size": len(tickers),
        "fingerprint": fp,
        "overview": overview,
        "summary": overview,
        "portfolio_sim": portfolio,
        "daily_signal_bars": daily_signal_bars(pool),
        "by_ticker": per_ticker,
        "final_day_signals": sorted(last_signals, key=lambda x: x.get("rsi_14", 0), reverse=True),
        "all_trades_count": len(pool),
    }
    if save_cache:
        save_study(fp, result)
    return result


def run_lab_matrix(
    rule_ids: list[str],
    cohort_specs: list[tuple[str, str, dict[str, Any]]],
    *,
    resolve_tickers_fn,
    cfg_override: dict | None = None,
) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for cohort_id, label, filt in cohort_specs:
        tickers = resolve_tickers_fn(filt)
        for rid in rule_ids:
            block = run_rule_study_universe(rid, tickers, cfg_override=cfg_override)
            cells.append(
                {
                    "cohort_id": cohort_id,
                    "cohort_label": label,
                    "n_tickers": len(tickers),
                    **block,
                }
            )
    return {"mode": "izanami_lab", "cells": cells}
