from signalforge.experiments.runner import _resume_rows_map
from signalforge.experiments.storage import compact_ticker_row, ticker_row_has_core_metrics


def test_ticker_row_has_core_metrics():
    assert ticker_row_has_core_metrics(
        {"avg_pnl_pct": 0.1, "max_drawdown_pct": -5.0, "total_trades": 10}
    )
    assert not ticker_row_has_core_metrics({"max_drawdown_pct": -5.0, "total_trades": 10})
    assert not ticker_row_has_core_metrics({"avg_pnl_pct": 0.1, "max_drawdown_pct": -5.0, "total_trades": 0})
    assert ticker_row_has_core_metrics({"error": "x"})


def test_resume_rows_map_skips_legacy_bug_rows():
    rows = [
        {
            "ticker": "7203.T",
            "avg_pnl_pct": -65.0,
            "max_drawdown_pct": -90.0,
            "profit_factor": 0.0,
            "total_trades": 5,
        },
        {"ticker": "9984.T", "avg_pnl_pct": 0.2, "max_drawdown_pct": -4.0, "total_trades": 8},
    ]
    m = _resume_rows_map(rows)
    assert list(m) == ["9984.T"]


def test_resume_rows_map_skips_incomplete():
    rows = [
        {"ticker": "7203.T", "profit_factor": 1.1, "max_drawdown_pct": -3.0, "total_trades": 4},
        {"ticker": "9984.T", "avg_pnl_pct": 0.2, "max_drawdown_pct": -4.0, "total_trades": 6},
    ]
    m = _resume_rows_map(rows)
    assert list(m) == ["9984.T"]


def test_compact_lifts_avg_from_nested_metrics():
    row = {
        "ticker": "7203.T",
        "metrics": {"avg_pnl_pct": 0.15, "max_drawdown_pct": -2.0, "profit_factor": 1.2},
    }
    out = compact_ticker_row(row)
    assert out["avg_pnl_pct"] == 0.15
    assert "metrics" not in out
