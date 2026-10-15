import pandas as pd

from signalforge.lab.portfolio_sim import simulate_diversified_portfolio
from signalforge.portfolio.diversified import (
    default_diversified_params,
    filter_trades_after,
    trades_pool_from_ticker_rows,
)


def test_default_params_match_tse_capital() -> None:
    p = default_diversified_params()
    assert p["initial_capital"] == 3_000_000.0
    assert p["max_positions"] == 5
    assert p["position_pct"] == 0.2


def test_pool_merge_and_greedy_cap() -> None:
    rows = [
        {
            "ticker": "7203.T",
            "trades_compact": [
                {"e": "2024-01-02", "x": "2024-01-10", "p": 5.0},
                {"e": "2024-02-01", "x": "2024-02-08", "p": 3.0},
            ],
        },
        {
            "ticker": "6758.T",
            "trades_compact": [{"e": "2024-01-03", "x": "2024-01-12", "p": -2.0}],
        },
    ]
    pool = trades_pool_from_ticker_rows(rows)
    assert len(pool) == 3
    sim = simulate_diversified_portfolio(pool, initial_capital=1_000_000, max_positions=1, position_pct=0.5)
    assert sim["accepted_trades"] <= 2
    assert sim["skipped_overlap"] >= 1


def test_filter_trades_after_cutoff() -> None:
    pool = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "exit_time": pd.to_datetime(["2024-01-10", "2024-02-10"]),
            "pnl_pct": [1.0, 2.0],
            "ticker": ["A", "B"],
        }
    )
    out = filter_trades_after(pool, pd.Timestamp("2024-01-15"))
    assert len(out) == 1
    assert out.iloc[0]["ticker"] == "B"
