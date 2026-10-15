"""Capital-constrained portfolio simulation."""

from __future__ import annotations

import pandas as pd

from signalforge.lab.portfolio_sim import simulate_diversified_portfolio


def _trade(ticker: str, entry: str, exit_: str, pnl_pct: float, sector: str = "") -> dict:
    return {
        "ticker": ticker,
        "entry_time": entry,
        "exit_time": exit_,
        "pnl_pct": pnl_pct,
        "sector_tse": sector,
    }


def test_sector_liquidity_caps_same_sector():
    trades = pd.DataFrame(
        [
            _trade("A", "2020-01-01", "2020-06-01", 10.0, "sec1"),
            _trade("B", "2020-01-01", "2020-06-01", 10.0, "sec1"),
            _trade("C", "2020-01-01", "2020-06-01", 10.0, "sec1"),
        ]
    )
    out = simulate_diversified_portfolio(
        trades,
        initial_capital=1_000_000,
        max_positions=5,
        position_pct=0.2,
        entry_priority="sector_liquidity",
        max_per_sector=2,
    )
    assert out["accepted_trades"] == 2
    assert out["skipped_overlap"] == 1


def test_liquidity_prefers_higher_score_on_same_day(monkeypatch):
    from signalforge.lab import portfolio_sim as ps

    monkeypatch.setattr(
        ps,
        "ticker_liquidity_score_map",
        lambda: {"LIQ": 100.0, "ILL": 1.0},
    )
    trades = pd.DataFrame(
        [
            _trade("ILL", "2020-01-01", "2020-02-01", 1.0),
            _trade("LIQ", "2020-01-01", "2020-02-01", 50.0),
        ]
    )
    liq = simulate_diversified_portfolio(
        trades,
        initial_capital=1_000_000,
        max_positions=1,
        position_pct=1.0,
        entry_priority="liquidity",
    )
    fc = simulate_diversified_portfolio(
        trades,
        initial_capital=1_000_000,
        max_positions=1,
        position_pct=1.0,
        entry_priority="first_come",
    )
    assert liq["accepted_trades"] == 1
    assert liq["final_equity"] > fc["final_equity"]
