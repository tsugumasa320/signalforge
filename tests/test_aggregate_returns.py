from signalforge.compare.runner import _aggregate


def test_aggregate_includes_return_medians():
    rows = [
        {"profit_factor": 1.2, "total_return_pct": 10.0, "win_rate": 0.5, "total_trades": 50},
        {"profit_factor": 0.9, "total_return_pct": -5.0, "win_rate": 0.4, "total_trades": 30},
    ]
    s = _aggregate(rows)
    assert s["median_total_return_pct"] == 2.5
    assert s["mean_return_pct"] == 2.5
    assert s["pct_return_above_0"] == 0.5
