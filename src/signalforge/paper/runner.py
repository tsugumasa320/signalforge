from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from signalforge.backtest.costs import load_cost_model
from signalforge.backtest.engine import BacktestEngine
from signalforge.backtest.metrics import compute_metrics
from signalforge.config import load_style_config
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.indicators.engine import IndicatorEngine
from signalforge.paper.portfolio import PaperPortfolio
from signalforge.pipeline import resolve_data_source
from signalforge.profiles.base import StyleProfile
from signalforge.strategies.registry import get_strategy


def _bar_index(df: pd.DataFrame, ts_str: str | None) -> int | None:
    if not ts_str:
        return None
    ts = pd.Timestamp(ts_str)
    if ts.tzinfo is None and df.index.tz is not None:
        ts = ts.tz_localize("UTC")
    if ts in df.index:
        return int(df.index.get_loc(ts))
    loc = df.index.searchsorted(ts, side="right") - 1
    return int(loc) if loc >= 0 else None


def _prepare_dataframe(style: str, cfg: dict[str, Any], refresh: bool) -> tuple[pd.DataFrame, str]:
    nvda = cfg.get("_nvda", {})
    ticker = nvda.get("ticker", "NVDA")
    corr = nvda.get("correlation_tickers", [])
    timeframe = cfg.get("timeframe", "1d")
    data_source = resolve_data_source(style, cfg)

    fetcher = MarketDataFetcher(data_source=data_source)
    cache = ParquetCache()
    try:
        df = cache.load_or_fetch(ticker, timeframe, fetcher, refresh=refresh)
    except Exception:
        if data_source == "alpaca":
            fetcher = MarketDataFetcher(data_source="yfinance")
            df = cache.load_or_fetch(ticker, timeframe, fetcher, refresh=refresh)
        else:
            raise

    qqq_df = soxx_df = None
    for sym in corr:
        try:
            cdf = cache.load_or_fetch(sym, timeframe, fetcher, refresh=refresh)
        except Exception:
            cdf = cache.load_or_fetch(sym, timeframe, MarketDataFetcher("yfinance"), refresh=refresh)
        if sym == "QQQ":
            qqq_df = cdf
        elif sym == "SOXX":
            soxx_df = cdf

    intraday = style == "daytrade" or style.startswith("daytrade")
    tz = nvda.get("timezone", "America/New_York")
    engine_ind = IndicatorEngine(timezone=tz)
    df = engine_ind.compute(df, intraday=intraday)
    if qqq_df is not None:
        qqq_df = engine_ind.compute(qqq_df, intraday=intraday)
    if soxx_df is not None:
        soxx_df = engine_ind.compute(soxx_df, intraday=intraday)

    return df, data_source


def _engine_state_from_portfolio(portfolio: PaperPortfolio, df: pd.DataFrame) -> dict[str, Any] | None:
    if not portfolio.position:
        return None
    pos = dict(portfolio.position)
    entry_ts = pos.pop("entry_time", None)
    entry_idx = _bar_index(df, entry_ts)
    if entry_idx is None:
        return None
    sig_ts = pos.get("entry_signal_time")
    sig_idx = _bar_index(df, sig_ts) if sig_ts else entry_idx - 1
    return {
        "cash": portfolio.cash,
        "position": 1,
        "position_shares": pos.get("position_shares", 0.0),
        "entry_price": pos.get("entry_price", 0.0),
        "entry_idx": entry_idx,
        "side": pos.get("side", "long"),
        "entry_signal_idx": sig_idx,
        "entry_is_oos": pos.get("entry_is_oos", False),
        "entry_ml_expl": pos.get("entry_ml_expl"),
        "cash_at_entry": pos.get("cash_at_entry", portfolio.cash),
        "entry_cost_breakdown": pos.get("entry_cost_breakdown", {}),
    }


def _save_position_from_state(portfolio: PaperPortfolio, state: dict[str, Any] | None, df: pd.DataFrame) -> None:
    if not state or int(state.get("position", 0)) == 0:
        portfolio.position = None
        return
    entry_idx = int(state.get("entry_idx", 0))
    sig_idx = state.get("entry_signal_idx")
    portfolio.position = {
        "position_shares": state.get("position_shares", 0.0),
        "entry_price": state.get("entry_price", 0.0),
        "entry_time": str(df.index[entry_idx]),
        "entry_signal_time": str(df.index[int(sig_idx)]) if sig_idx is not None else str(df.index[max(entry_idx - 1, 0)]),
        "side": state.get("side", "long"),
        "entry_is_oos": state.get("entry_is_oos", False),
        "entry_ml_expl": state.get("entry_ml_expl"),
        "cash_at_entry": state.get("cash_at_entry", portfolio.cash),
        "entry_cost_breakdown": state.get("entry_cost_breakdown", {}),
    }


def init_paper_portfolio(
    style: str,
    strategy: str | None = None,
    *,
    cost_model: str = "alpaca",
    refresh: bool = True,
) -> PaperPortfolio:
    cfg = load_style_config(style)
    strategy = strategy or cfg.get("strategy", "ema_pullback")
    df, _ = _prepare_dataframe(style, cfg, refresh)
    if df.empty:
        raise RuntimeError("データが取得できませんでした。")

    from signalforge.config import CONFIG_DIR, load_yaml

    alpaca_cfg = load_yaml(CONFIG_DIR / "costs" / "alpaca.yaml")
    initial_cash = float(alpaca_cfg.get("initial_cash_usd", 100_000))

    last_ts = str(df.index[-1])
    portfolio = PaperPortfolio.create(
        style,
        strategy,
        cost_model=cost_model,
        initial_cash=initial_cash,
        last_bar_ts=last_ts,
    )
    portfolio.equity_snapshots.append(
        {
            "date": last_ts,
            "equity": initial_cash,
            "cash": initial_cash,
            "note": "paper 開始（この時点以降の足だけ仮想売買）",
        }
    )
    portfolio.save()
    return portfolio


def run_paper_daily(
    style: str,
    strategy: str | None = None,
    *,
    cost_model: str | None = None,
    refresh: bool = True,
    ml_filter: bool = False,
) -> dict[str, Any]:
    cfg = load_style_config(style)
    strategy = strategy or cfg.get("strategy", "ema_pullback")
    portfolio = PaperPortfolio.load(style, strategy)
    if portfolio is None:
        portfolio = init_paper_portfolio(style, strategy, cost_model=cost_model or "alpaca", refresh=refresh)

    cost_model = cost_model or portfolio.cost_model
    df, data_source = _prepare_dataframe(style, cfg, refresh)
    if df.empty:
        raise RuntimeError("データが取得できませんでした。")

    last_idx = _bar_index(df, portfolio.last_processed_bar)
    if last_idx is None:
        last_idx = -1

    start_idx = last_idx + 1
    if start_idx >= len(df):
        last_close = float(df.iloc[-1]["close"])
        equity = portfolio.mark_to_market_equity(last_close)
        return {
            "status": "up_to_date",
            "message": "新しい足はまだありません。",
            "portfolio": portfolio,
            "equity": equity,
            "data_source": data_source,
            "last_bar": str(df.index[-1]),
            "new_bars": 0,
        }

    profile = StyleProfile.from_config(cfg)
    strat = get_strategy(strategy, cfg)
    signals = strat.generate_signals(df)

    engine = BacktestEngine(
        profile,
        strat,
        cfg,
        ml_filter=None if not ml_filter else None,  # ML は paper 初版では TA のみ
        cost_model=load_cost_model(cost_model, style, cfg.get("_defaults")),
    )

    initial_state = _engine_state_from_portfolio(portfolio, df)
    result = engine.run(
        df,
        signals=signals,
        start_idx=start_idx,
        initial_cash=portfolio.cash,
        initial_state=initial_state,
    )

    new_trades = result.trades.to_dict("records") if not result.trades.empty else []
    for t in new_trades:
        t["entry_time"] = str(t.get("entry_time", ""))
        t["exit_time"] = str(t.get("exit_time", ""))
        portfolio.closed_trades.append(t)

    portfolio.cash = float(result.final_cash or portfolio.cash)
    _save_position_from_state(portfolio, result.final_state, df)

    last_bar = str(df.index[-1])
    last_close = float(df.iloc[-1]["close"])
    equity = portfolio.mark_to_market_equity(last_close)
    portfolio.last_processed_bar = last_bar
    portfolio.last_run_at = datetime.now(timezone.utc).isoformat()

    portfolio.equity_snapshots.append(
        {
            "date": last_bar,
            "equity": equity,
            "cash": portfolio.cash,
            "position": portfolio.position.get("side") if portfolio.position else "flat",
            "new_trades": len(new_trades),
        }
    )
    portfolio.daily_log.append(
        {
            "run_at": portfolio.last_run_at,
            "bars_processed": len(df) - start_idx,
            "from_bar": str(df.index[start_idx]),
            "to_bar": last_bar,
            "new_trades": len(new_trades),
        }
    )
    portfolio.save()

    closed_df = pd.DataFrame(portfolio.closed_trades)
    if not closed_df.empty and "entry_time" in closed_df.columns:
        closed_df["entry_time"] = pd.to_datetime(closed_df["entry_time"])
        if "exit_time" in closed_df.columns:
            closed_df["exit_time"] = pd.to_datetime(closed_df["exit_time"])

    eq_series = pd.Series(
        [s["equity"] for s in portfolio.equity_snapshots],
        index=pd.to_datetime([s["date"] for s in portfolio.equity_snapshots]),
    )
    metrics = compute_metrics(closed_df, eq_series) if not closed_df.empty else compute_metrics(closed_df, eq_series)
    total_return = (equity / portfolio.initial_cash - 1) * 100 if portfolio.initial_cash else 0.0

    return {
        "status": "ok",
        "portfolio": portfolio,
        "new_trades": new_trades,
        "new_bars": len(df) - start_idx,
        "metrics": metrics,
        "equity": equity,
        "total_return_pct": total_return,
        "data_source": data_source,
        "last_bar": last_bar,
        "position": portfolio.position,
    }
