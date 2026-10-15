from signalforge.backtest.capital import CapitalPolicy
from signalforge.config import load_style_config


def test_paper_init_uses_japan_capital_policy() -> None:
    cfg = load_style_config("swing")
    policy = CapitalPolicy.from_config(cfg)
    assert policy.currency == "JPY"
    assert policy.initial_cash == 3_000_000.0
