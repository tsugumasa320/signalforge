from signalforge.backtest.capital import capital_records_match, resolve_experiment_capital
from signalforge.experiments.runner import strategy_needs_capital_refresh


def test_capital_records_match():
    a = {"initial_cash_jpy": 3_000_000, "max_position_pct": 0.35, "min_cash_reserve_pct": 0.1, "currency": "JPY"}
    b = dict(a)
    assert capital_records_match(a, b)
    assert not capital_records_match(a, {**a, "max_position_pct": 0.5})


def test_resolve_experiment_capital_cli_override():
    p = resolve_experiment_capital(initial_cash_jpy=5_000_000, max_position_pct=0.25)
    assert p.initial_cash == 5_000_000
    assert p.max_position_pct == 0.25


def test_strategy_needs_capital_refresh(tmp_path, monkeypatch):
    from signalforge.experiments import runner as r

    strat = tmp_path / "strategies"
    strat.mkdir()
    sid = "foo"
    (strat / f"{sid}.json").write_text(
        '{"strategy_id":"foo","complete":true,"backtest_capital":{"initial_cash_jpy":3000000,'
        '"max_position_pct":1.0,"min_cash_reserve_pct":0.0,"currency":"JPY"}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(r, "experiments_dir", lambda: tmp_path)
    monkeypatch.setattr(r, "_strategy_path", lambda s: strat / f"{s}.json")

    from signalforge.experiments import storage as st

    monkeypatch.setattr(st, "_strategies_dir", lambda: strat)
    current = {
        "initial_cash_jpy": 3_000_000,
        "max_position_pct": 0.35,
        "min_cash_reserve_pct": 0.0,
        "currency": "JPY",
    }
    assert strategy_needs_capital_refresh(sid, current) is True
    assert strategy_needs_capital_refresh(sid, {**current, "max_position_pct": 1.0}) is False
