from signalforge import pipeline


def test_strategy_exit_overrides_style_defaults(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "_strategy_exit_map",
        lambda: {"mr": {"atr_sl_multiple": 3.0, "max_hold_bars": 20}},
    )
    cfg = {"rules": {"exit": {"atr_tp_multiple": 3.0, "atr_sl_multiple": 1.5}}, "backtest": {"max_hold_bars": 15}}
    pipeline._apply_strategy_exit(cfg, "mr")
    assert cfg["rules"]["exit"] == {"atr_tp_multiple": 3.0, "atr_sl_multiple": 3.0, "max_hold_bars": 20}
    assert cfg["backtest"]["max_hold_bars"] == 20

    other = {"rules": {"exit": {"atr_sl_multiple": 1.5}}, "backtest": {"max_hold_bars": 15}}
    pipeline._apply_strategy_exit(other, "unknown")
    assert other["backtest"]["max_hold_bars"] == 15


def test_drop_broken_trades():
    import pandas as pd

    from signalforge.portfolio.diversified import drop_broken_trades

    pool = pd.DataFrame({"pnl_pct": [1.0, -5.0, 24000.0]})
    assert drop_broken_trades(pool)["pnl_pct"].tolist() == [1.0, -5.0]
