import numpy as np
import pandas as pd
import pytest

from signalforge.indicators.engine import IndicatorEngine, daily_vwap
from signalforge.interpret.audit import RuleCheck, SignalAudit
from signalforge.interpret.features_registry import allowed_feature_names, validate_features
from signalforge.profiles.swing import SwingProfile


def _sample_ohlcv(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-02", periods=n, freq="D", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n),
        },
        index=idx,
    )
    return df


def test_vwap_reset():
    idx = pd.date_range("2024-01-02 09:30", periods=20, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100] * 20,
            "high": [101] * 20,
            "low": [99] * 20,
            "close": [100] * 20,
            "volume": [1000] * 10 + [2000] * 10,
        },
        index=idx,
    )
    vwap = daily_vwap(df)
    assert not vwap.isna().all()
    assert len(vwap) == 20


def test_no_lookahead():
    df = _sample_ohlcv(80)
    engine = IndicatorEngine(shift=1)
    out = engine.compute(df, intraday=False)
    assert out["ema20"].iloc[1:].notna().sum() > 0
    assert pd.isna(out["ema20"].iloc[0]) or out["ema20"].iloc[0] != df["close"].iloc[0]


def test_signal_audit():
    audit = SignalAudit()
    from signalforge.interpret.audit import SignalAuditResult

    audit.record(
        SignalAuditResult(
            timestamp="2024-01-02",
            side="long",
            all_passed=False,
            checks=[
                RuleCheck("close > ema200", True),
                RuleCheck("adx > 25", False, detail="adx > 25 (actual: 18.3)"),
            ],
        )
    )
    assert len(audit.records) == 1
    assert "adx > 25 (actual: 18.3)" in audit.records[0].failed_rules


def test_swing_overnight():
    profile = SwingProfile(
        name="swing",
        timeframe="1d",
        max_hold_bars=15,
        slippage_pct=0.0005,
        fill_mode="next_day_open",
    )
    df = _sample_ohlcv(10)
    price = profile.entry_fill_price(df, 0, "long")
    assert price > 0
    assert profile.should_force_exit(df, 5, 15) is True
    assert profile.should_force_exit(df, 5, 5) is False


def test_features_registry():
    names = allowed_feature_names()
    assert "adx_14" in names
    validate_features(["adx_14", "rsi_14"])


def test_backtest_swing_smoke():
    from signalforge.pipeline import run_backtest_pipeline

    result = run_backtest_pipeline("swing", "ema_pullback", refresh_data=True)
    assert "metrics" in result
    assert "run_id" in result
    assert result["metrics"]["total_trades"] >= 0


def test_shap_output_structure():
    from signalforge.interpret.features_registry import get_feature_descriptions

    desc = get_feature_descriptions()
    assert "adx_14" in desc
    assert isinstance(desc["adx_14"], str)


def test_walk_forward_ml_prepare():
    from signalforge.config import load_style_config
    from signalforge.ml.filter import MetaLabelFilter
    from signalforge.pipeline import run_backtest_pipeline
    from signalforge.strategies.registry import get_strategy

    result = run_backtest_pipeline("swing", "ema_pullback")
    df = result["df"]
    cfg = load_style_config("swing")
    cfg["ml_filter"] = {**cfg.get("ml_filter", {}), "enabled": True}
    strategy = get_strategy("ema_pullback", cfg)
    signals = strategy.generate_signals(df)

    meta = MetaLabelFilter(cfg["ml_filter"])
    report = meta.prepare(df, signals, exit_rules=cfg.get("rules", {}).get("exit", {}))
    assert report.get("trained") is True
    assert report.get("folds", 0) >= 1
    assert len(meta._folds) >= 1


def test_ml_oos_metrics_not_inflated():
    from signalforge.pipeline import run_backtest_pipeline

    ta = run_backtest_pipeline("swing", "ema_pullback")
    ml = run_backtest_pipeline("swing", "ema_pullback", ml_filter=True)
    oos = ml.get("metrics_oos", {})
    # OOS PF should not wildly exceed full-sample TA PF (old bug showed 4+ vs 1.07)
    if oos.get("total_trades", 0) > 0:
        assert oos["profit_factor"] < ta["metrics"]["profit_factor"] * 3
    assert ml.get("ml_report", {}).get("trained") is True


def test_macd_long_only_skips_short():
    import pandas as pd

    from signalforge.strategies.swing.macd_cross import MacdCrossStrategy

    idx = pd.date_range("2024-01-02", periods=5, freq="D", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104],
            "high": [101, 102, 103, 104, 105],
            "low": [99, 100, 101, 102, 103],
            "close": [100, 101, 102, 103, 104],
            "volume": [1_000_000] * 5,
            "macd": [0.1, 0.2, -0.1, -0.2, -0.3],
            "macd_signal": [0.15, 0.18, 0.0, -0.1, -0.15],
            "ema50": [99, 100, 101, 102, 103],
            "adx_14": [30] * 5,
        },
        index=idx,
    )
    cfg = {"strategy_params": {"long_only": True, "adx_min": 20, "ema_trend": 50}}
    sig = MacdCrossStrategy(cfg).generate_signals(df)
    assert (sig >= 0).all()


def test_optimize_cfg_override():
    from signalforge.config import load_style_config
    from signalforge.optimize.spaces import build_cfg_override

    base = load_style_config("swing")
    params = {
        "adx_threshold": 22,
        "atr_tp_multiple": 3.5,
        "atr_sl_multiple": 1.25,
        "max_hold_bars": 12,
    }
    override = build_cfg_override("ema_pullback", params, base)
    assert "adx > 22" in override["rules"]["long"][-1]
    assert override["rules"]["exit"]["atr_tp_multiple"] == 3.5
    assert override["backtest"]["max_hold_bars"] == 12


def test_alpaca_regulatory_fees():
    from signalforge.backtest.costs import AlpacaCostModel

    model = AlpacaCostModel()
    sec, taf, cat, comm = model.sell_fees(100, 50.0)
    assert sec == 0.11  # 5000 * 0.0000206 = 0.103 → $0.01 rounding... 0.103 ceil = 0.11
    assert taf == 0.02
    assert cat == 0.01
    assert comm == 0.0
    assert model.buy_fees(100) == 0.01


def test_backtest_window_trim():
    import pandas as pd

    from signalforge.data.window import trim_to_backtest_window

    idx = pd.date_range("2022-01-01", periods=500, freq="D", tz="UTC")
    df = pd.DataFrame({"close": range(500)}, index=idx)
    out = trim_to_backtest_window(df, pd.Timestamp("2023-01-01"), None)
    assert out.index.min() >= pd.Timestamp("2023-01-01", tz="UTC")
    assert len(out) < len(df)


def test_pickle_cache_roundtrip(tmp_path):
    from signalforge.data.cache import ParquetCache

    idx = pd.date_range("2024-01-02", periods=5, freq="D", tz="UTC")
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=idx)
    cache = ParquetCache(base=tmp_path)
    cache.save("NVDA", "1d", df)
    loaded = cache.load("NVDA", "1d")
    assert loaded is not None
    assert len(loaded) == 5
    assert cache.path("NVDA", "1d").suffix == ".pkl"


def test_paper_portfolio_save_load(tmp_path, monkeypatch):
    from signalforge.paper.portfolio import PaperPortfolio, paper_dir

    monkeypatch.setattr("signalforge.paper.portfolio.data_dir", lambda: tmp_path)
    p = PaperPortfolio.create("swing", "ema_pullback", last_bar_ts="2026-08-01T00:00:00Z")
    p.save()
    loaded = PaperPortfolio.load("swing", "ema_pullback")
    assert loaded is not None
    assert loaded.strategy == "ema_pullback"
    assert loaded.last_processed_bar == "2026-08-01T00:00:00Z"
    assert paper_dir().exists()
