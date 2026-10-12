from signalforge.experiments.storage import compact_ticker_row


def test_compact_ticker_row_drops_nested_metrics():
    row = {
        "ticker": "7203.T",
        "profit_factor": 1.2,
        "metrics": {"profit_factor": 1.2},
        "metrics_oos": {},
        "metrics_in_sample": {},
    }
    out = compact_ticker_row(row)
    assert out["profit_factor"] == 1.2
    assert "metrics" not in out


def test_strategy_run_order_ml_last():
    from signalforge.experiments.order import sort_strategies_for_campaign

    cat = {
        "a": {"style": "swing_champion"},
        "b": {"style": "swing"},
        "c": {"style": "swing_high_winrate"},
    }
    ordered = sort_strategies_for_campaign(["a", "b", "c"], cat)
    assert ordered.index("b") < ordered.index("a")
    assert ordered.index("b") < ordered.index("c")
