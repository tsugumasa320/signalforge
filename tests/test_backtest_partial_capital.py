"""Partial position sizing must not distort per-trade pnl_pct."""

from signalforge.pipeline import run_backtest_pipeline


def test_partial_capital_pnl_not_full_account_sized():
    r = run_backtest_pipeline(
        "swing",
        "ema_pullback",
        cfg_override={
            "ticker": "7203.T",
            "backtest": {"capital": {"initial_cash_jpy": 3_000_000, "max_position_pct": 0.35}},
        },
        cost_model="japan",
        slim_return=True,
    )
    m = r["metrics"]
    assert m["total_trades"] > 0
    # Bug regression: was ~-65% per trade when dividing by full 3M cash
    assert m["avg_pnl_pct"] > -20.0
    assert m["max_drawdown_pct"] > -99.0
