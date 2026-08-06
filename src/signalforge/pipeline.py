from __future__ import annotations

import os
from typing import Any

import pandas as pd

from signalforge.backtest.costs import load_cost_model
from signalforge.backtest.engine import BacktestEngine
from signalforge.config import load_style_config
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.data.window import (
    resolve_backtest_dates,
    slice_for_indicators,
    trim_to_backtest_window,
    window_label,
)
from signalforge.indicators.engine import IndicatorEngine
from signalforge.interpret.journal import compute_oos_metrics
from signalforge.ml.filter import MetaLabelFilter
from signalforge.profiles.base import StyleProfile
from signalforge.strategies.registry import get_strategy


def resolve_data_source(style: str, cfg: dict[str, Any]) -> str:
    preferred = cfg.get("data_source", "yfinance")
    if preferred == "alpaca" or style == "daytrade":
        if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"):
            return "alpaca"
    return "yfinance"


def run_backtest_pipeline(
    style: str,
    strategy_name: str | None = None,
    refresh_data: bool = False,
    ml_filter: bool = False,
    cfg_override: dict[str, Any] | None = None,
    cost_model: str = "alpaca",
) -> dict[str, Any]:
    cfg = load_style_config(style)
    if cfg_override:
        for key, value in cfg_override.items():
            if key == "rules" and isinstance(value, dict):
                base_rules = cfg.get("rules", {})
                merged = {**base_rules, **value}
                if "exit" in value and isinstance(value["exit"], dict):
                    merged["exit"] = {**base_rules.get("exit", {}), **value["exit"]}
                cfg["rules"] = merged
            elif key == "strategy_params" and isinstance(value, dict):
                cfg["strategy_params"] = {**cfg.get("strategy_params", {}), **value}
            elif key == "backtest" and isinstance(value, dict):
                cfg["backtest"] = {**cfg.get("backtest", {}), **value}
            elif key == "ml_filter" and isinstance(value, dict):
                cfg["ml_filter"] = {**cfg.get("ml_filter", {}), **value}
            else:
                cfg[key] = value

    strategy_name = strategy_name or cfg.get("strategy", "ema_pullback")
    nvda = cfg.get("_nvda", {})
    ticker = nvda.get("ticker", "NVDA")
    corr = nvda.get("correlation_tickers", [])
    timeframe = cfg.get("timeframe", "1d")
    data_source = resolve_data_source(style, cfg)

    fetcher = MarketDataFetcher(data_source=data_source)
    cache = ParquetCache()

    try:
        df = cache.load_or_fetch(ticker, timeframe, fetcher, refresh=refresh_data)
    except Exception:
        if data_source == "alpaca":
            fetcher = MarketDataFetcher(data_source="yfinance")
            df = cache.load_or_fetch(ticker, timeframe, fetcher, refresh=refresh_data)
        else:
            raise

    qqq_df = soxx_df = None
    for sym in corr:
        try:
            cdf = cache.load_or_fetch(sym, timeframe, fetcher, refresh=refresh_data)
        except Exception:
            cdf = cache.load_or_fetch(sym, timeframe, MarketDataFetcher("yfinance"), refresh=refresh_data)
        if sym == "QQQ":
            qqq_df = cdf
        elif sym == "SOXX":
            soxx_df = cdf

    bt_start, bt_end = resolve_backtest_dates(cfg)
    df = slice_for_indicators(df, bt_start)
    if qqq_df is not None:
        qqq_df = slice_for_indicators(qqq_df, bt_start)
    if soxx_df is not None:
        soxx_df = slice_for_indicators(soxx_df, bt_start)

    intraday = style == "daytrade" or style.startswith("daytrade")
    engine_ind = IndicatorEngine(timezone=nvda.get("timezone", "America/New_York"))
    df = engine_ind.compute(df, intraday=intraday)
    if qqq_df is not None:
        qqq_df = engine_ind.compute(qqq_df, intraday=intraday)
    if soxx_df is not None:
        soxx_df = engine_ind.compute(soxx_df, intraday=intraday)

    df = trim_to_backtest_window(df, bt_start, bt_end)
    if qqq_df is not None:
        qqq_df = trim_to_backtest_window(qqq_df, bt_start, bt_end)
    if soxx_df is not None:
        soxx_df = trim_to_backtest_window(soxx_df, bt_start, bt_end)

    profile = StyleProfile.from_config(cfg)
    strategy = get_strategy(strategy_name, cfg)
    signals = strategy.generate_signals(df)

    ml_cfg = cfg.get("ml_filter", {}).copy()
    if ml_filter or ml_cfg.get("enabled"):
        ml_cfg["enabled"] = True

    meta: MetaLabelFilter | None = None
    ml_report: dict[str, Any] = {"trained": False}
    if ml_cfg.get("enabled"):
        meta = MetaLabelFilter(ml_cfg, intraday=intraday)
        ml_report = meta.prepare(
            df,
            signals,
            qqq_df,
            soxx_df,
            exit_rules=cfg.get("rules", {}).get("exit", {}),
        )

    bt_engine = BacktestEngine(
        profile,
        strategy,
        cfg,
        ml_filter=meta,
        cost_model=load_cost_model(cost_model, style, cfg.get("_defaults")),
    )
    result = bt_engine.run(df, signals=signals)

    oos_metrics = compute_oos_metrics(bt_engine.journal, result.equity_curve)
    in_sample_trades = (
        result.trades[~result.trades["is_oos"]]
        if not result.trades.empty and "is_oos" in result.trades.columns
        else result.trades
    )
    from signalforge.backtest.metrics import compute_metrics

    in_sample_metrics = (
        compute_metrics(in_sample_trades, result.equity_curve) if not in_sample_trades.empty else result.metrics
    )

    reports_dir = cache.base / "reports"
    bt_engine.journal.save(reports_dir)

    return {
        "metrics": result.metrics,
        "metrics_oos": oos_metrics,
        "metrics_in_sample": in_sample_metrics,
        "run_id": result.journal_run_id,
        "trades": result.trades,
        "equity": result.equity_curve,
        "df": df,
        "ml_report": ml_report,
        "journal": bt_engine.journal,
        "strategy": strategy_name,
        "style": style,
        "data_source": data_source,
        "cost_model": cost_model,
        "backtest_window": window_label(bt_start, bt_end, len(df)),
        "backtest_start": str(bt_start.date()) if bt_start is not None else None,
        "backtest_end": str(bt_end.date()) if bt_end is not None else None,
    }
