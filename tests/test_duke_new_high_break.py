"""DUKE。新高値ブレイク — シグナルと % ストップの回帰テスト。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from signalforge.backtest.engine import BacktestEngine
from signalforge.profiles.swing import SwingProfile
from signalforge.strategies.catalog_template import CatalogTemplateStrategy, _duke_new_high_break
from signalforge.strategies.base import BaseStrategy


class _Dummy(BaseStrategy):
    name = "dummy"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(0, index=df.index)


def _ohlcv(n: int = 320, breakout_at: int = 280) -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    open_ = np.full(n, 100.0)
    # Peak ~50 bars before breakout (inside lookback, outside min_base_bars)
    peak = breakout_at - 50
    high[peak] = 105.0
    close[peak] = 104.0
    for i in range(breakout_at, n):
        close[i] = 100 + (i - breakout_at + 1) * 2.0
        high[i] = close[i] + 0.5
        low[i] = close[i] - 0.5
        open_[i] = close[i] - 0.2
    high[breakout_at] = 112.0
    close[breakout_at] = 111.0
    open_[breakout_at] = 105.0
    vol = np.full(n, 1_000_000.0)
    vol[breakout_at] = 3_000_000.0
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "volume_ratio_20": vol / 1_000_000.0,
            "atr_14": np.full(n, 1.5),
        },
        index=idx,
    )


def test_duke_signal_fires_on_fresh_high_break():
    df = _ohlcv()
    signals = _duke_new_high_break(
        df,
        {
            "lookback": 120,
            "volume_ratio_min": 1.5,
            "box_lookback": 40,
            "max_box_range_pct": 0.50,
            "min_base_bars": 15,
            "require_bullish_close": True,
            "require_stage2": False,
            "require_fund": False,
        },
        _Dummy({}),
    )
    assert int(signals.sum()) >= 1
    assert signals.iloc[280] == 1


def test_duke_stage2_filters_out_flat_base_break():
    """Stage2 requires rising SMA stack — flat 100-base breakout should not pass."""
    df = _ohlcv(n=400, breakout_at=360)
    signals = _duke_new_high_break(
        df,
        {
            "lookback": 120,
            "volume_ratio_min": 1.5,
            "box_lookback": 40,
            "max_box_range_pct": 0.50,
            "min_base_bars": 15,
            "require_bullish_close": True,
            "require_stage2": True,
            "require_market_rs": False,
            "require_fund": False,
        },
        _Dummy({}),
    )
    assert int(signals.sum()) == 0


def test_duke_stage2_passes_uptrend_break():
    n, breakout_at = 420, 380
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    # Smooth uptrend so SMA50>150>200, 200 rising, and ≥25% off the 52w low
    close = np.linspace(40.0, 140.0, n)
    high = close + 1.0
    low = close - 1.0
    open_ = close - 0.3
    # Quiet base then breakout above prior 120d high
    close[breakout_at - 40 : breakout_at] = close[breakout_at - 41]
    high[breakout_at - 40 : breakout_at] = close[breakout_at - 40 : breakout_at] + 0.5
    low[breakout_at - 40 : breakout_at] = close[breakout_at - 40 : breakout_at] - 0.5
    # Ensure ≥25% off the lookback low (図23-⑤)
    low[breakout_at - 90] = float(close[breakout_at - 90]) * 0.55
    prior_peak = float(high[breakout_at - 120 : breakout_at].max())
    close[breakout_at] = prior_peak + 3.0
    high[breakout_at] = prior_peak + 4.0
    open_[breakout_at] = prior_peak + 0.5
    low[breakout_at] = prior_peak + 0.2
    vol = np.full(n, 1e6)
    vol[breakout_at] = 3e6
    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "volume_ratio_20": vol / 1e6,
            "atr_14": np.full(n, 1.5),
            "market_rs_30d": np.full(n, 5.0),
        },
        index=idx,
    )
    signals = _duke_new_high_break(
        df,
        {
            "lookback": 120,
            "volume_ratio_min": 1.5,
            "box_lookback": 40,
            "max_box_range_pct": 0.50,
            "min_base_bars": 15,
            "require_bullish_close": True,
            "require_stage2": True,
            "require_market_rs": True,
            "require_fund": False,
            "sma200_up_bars": 21,
        },
        _Dummy({}),
    )
    assert signals.iloc[breakout_at] == 1


def test_pct_stop_and_breakeven_exit():
    idx = pd.date_range("2024-01-01", periods=12, freq="B")
    # Signal on bar 0; entry open bar 1 @ 100; then rises to +25% then dumps to 99
    rows = []
    closes = [100, 100, 105, 110, 125, 130, 99, 98, 97, 96, 95, 94]
    for i, c in enumerate(closes):
        rows.append(
            {
                "open": 100.0 if i == 1 else c,
                "high": max(c, 100.0 if i == 1 else c) + (25 if i == 4 else 0),
                "low": min(c, 99.0 if i == 6 else c),
                "close": c,
                "volume": 1e6,
                "atr_14": 1.0,
            }
        )
    df = pd.DataFrame(rows, index=idx)
    signals = pd.Series(0, index=idx)
    signals.iloc[0] = 1

    cfg = {
        "rules": {
            "exit": {
                "use_atr_exits": False,
                "stop_loss_pct": 0.10,
                "breakeven_trigger_pct": 0.20,
                "box_stop_lookback": 0,
            }
        },
        "backtest": {"max_hold_bars": 50, "capital": {"initial_cash_jpy": 1_000_000}},
        "_defaults": {"commission_pct": 0.0},
    }
    profile = SwingProfile.from_config(cfg)
    strat = CatalogTemplateStrategy({**cfg, "_catalog_template": "momentum_ema", "_catalog_id": "t"})
    engine = BacktestEngine(profile, strat, cfg)
    result = engine.run(df, signals=signals)
    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    # After +20% arming, stop is entry (~100); day with low 99 should exit near breakeven
    assert trade["reason"] in {"breakeven_stop", "stop_loss"}
    assert abs(float(trade["pnl_pct"])) < 5.0


def test_pyramid_scales_in_on_profit_only():
    """試し玉1/5 → 含み益で同額買い増し。下落局面ではナンピンしない。"""
    idx = pd.date_range("2024-01-01", periods=16, freq="B")
    # entry open bar1=100; climb so adds fire; dump to arm exit
    closes = [100, 100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 90, 89, 88, 87]
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "open": 100.0 if i == 1 else float(c),
                "high": float(c) + 1.0,
                "low": float(c) - (12.0 if i == 12 else 0.5),
                "close": float(c),
                "volume": 1e6,
                "atr_14": 1.0,
            }
        )
    df = pd.DataFrame(rows, index=idx)
    signals = pd.Series(0, index=idx)
    signals.iloc[0] = 1

    cfg = {
        "rules": {
            "exit": {
                "use_atr_exits": False,
                "stop_loss_pct": 0.10,
                "breakeven_trigger_pct": 0.50,
                "box_stop_lookback": 0,
                "pyramid_tranches": 5,
            }
        },
        "backtest": {
            "max_hold_bars": 50,
            "capital": {"initial_cash_jpy": 1_000_000, "max_position_pct": 1.0},
            "slippage_pct": 0.0,
        },
        "_defaults": {"commission_pct": 0.0},
    }
    profile = SwingProfile.from_config(cfg)
    strat = CatalogTemplateStrategy({**cfg, "_catalog_template": "momentum_ema", "_catalog_id": "t"})
    engine = BacktestEngine(profile, strat, cfg)
    result = engine.run(df, signals=signals)
    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert int(trade["pyramid_filled"]) == 5
    assert int(trade["pyramid_adds"]) == 4

    # Underwater path: price never above entry → no adds
    closes2 = [100, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88, 87, 86]
    rows2 = []
    for i, c in enumerate(closes2):
        rows2.append(
            {
                "open": 100.0 if i == 1 else float(c),
                "high": float(c) + 0.2,
                "low": float(c) - 0.2,
                "close": float(c),
                "volume": 1e6,
                "atr_14": 1.0,
            }
        )
    df2 = pd.DataFrame(rows2, index=idx)
    signals2 = pd.Series(0, index=idx)
    signals2.iloc[0] = 1
    engine2 = BacktestEngine(profile, strat, cfg)
    result2 = engine2.run(df2, signals=signals2)
    assert len(result2.trades) == 1
    t2 = result2.trades.iloc[0]
    assert int(t2["pyramid_adds"]) == 0
    assert int(t2["pyramid_filled"]) == 1
