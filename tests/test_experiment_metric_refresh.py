from signalforge.experiments.runner import strategy_needs_metric_refresh


def test_strategy_needs_metric_refresh_when_missing_fields(tmp_path, monkeypatch):
    from signalforge.experiments import runner as r

    strat = tmp_path / "strategies"
    strat.mkdir()
    sid = "foo"
    (strat / f"{sid}.json").write_text(
        '{"strategy_id":"foo","complete":true,"n_tickers_target":1,"n_tickers_done":1,'
        '"universe":{},"metrics_schema":{"pnl_basis":"entry_cost_v3"}}',
        encoding="utf-8",
    )
    (strat / f"{sid}.tickers.json").write_text(
        '[{"ticker":"7203.T","profit_factor":1.1,"win_rate":0.5,"total_trades":10}]',
        encoding="utf-8",
    )

    def _dir():
        return strat

    monkeypatch.setattr(r, "experiments_dir", lambda: tmp_path)
    monkeypatch.setattr(r, "_strategy_path", lambda s: strat / f"{s}.json")
    monkeypatch.setattr(
        r,
        "load_strategy_header",
        lambda s: __import__("json").loads((strat / f"{s}.json").read_text()),
    )
    from signalforge.experiments import storage as st

    monkeypatch.setattr(st, "_strategies_dir", lambda: strat)
    assert strategy_needs_metric_refresh(sid) is True

    (strat / f"{sid}.tickers.json").write_text(
        '[{"ticker":"7203.T","profit_factor":1.1,"total_trades":10,'
        '"avg_pnl_pct":0.2,"max_drawdown_pct":-5.0}]',
        encoding="utf-8",
    )
    assert strategy_needs_metric_refresh(sid) is False
