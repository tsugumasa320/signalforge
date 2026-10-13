from signalforge.backtest.capital import CapitalPolicy


def test_entry_budget_reserve_and_cap():
    p = CapitalPolicy(initial_cash=1_000_000, max_position_pct=0.5, min_cash_reserve_pct=0.1)
    # cash 1M, reserve 100k, cap 500k -> 500k
    assert p.entry_budget(1_000_000) == 500_000
    # cash 200k left, reserve 20k, cap 500k on 1M equity -> min(180k, 500k)=180k
    assert p.entry_budget(200_000, equity=1_000_000) == 180_000


def test_from_config_japan_market_hint():
    cfg = {
        "_defaults": {"capital": {"initial_cash_jpy": 3_000_000, "max_position_pct": 1.0}},
        "_market": {
            "currency": "JPY",
            "cost_preset": "japan",
            "backtest_capital_hint": {"max_position_pct": 0.35, "min_cash_reserve_pct": 0.1},
        },
        "backtest": {},
    }
    p = CapitalPolicy.from_config(cfg)
    assert p.initial_cash == 3_000_000
    assert p.max_position_pct == 0.35
    assert p.min_cash_reserve_pct == 0.1
