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


def test_fills_keep_ticker_dates_and_prices():
    trades = pd.DataFrame(
        [
            {
                **_trade("7203.T", "2024-01-02", "2024-01-05", 4.0, "輸送用機器"),
                "entry_price": 2500.0,
                "exit_price": 2600.0,
            }
        ]
    )
    out = simulate_diversified_portfolio(
        trades,
        initial_capital=1_000_000,
        max_positions=1,
        position_pct=0.2,
        entry_priority="first_come",
    )
    fills = out["fills"]
    assert len(fills) == 1
    assert fills[0]["ticker"] == "7203.T"
    assert fills[0]["entry_time"] == "2024-01-02"
    assert fills[0]["exit_time"] == "2024-01-05"
    assert fills[0]["entry_price"] == 2500.0
    assert fills[0]["exit_price"] == 2600.0
    assert fills[0]["pnl_jpy"] > 0


def test_turnover_priority_and_floor():
    trades = pd.DataFrame(
        [
            {**_trade("THIN", "2020-01-01", "2020-02-01", 30.0, "a"), "turnover_jpy": 1e7},
            {**_trade("MID", "2020-01-01", "2020-02-01", 5.0, "b"), "turnover_jpy": 6e8},
            {**_trade("BIG", "2020-01-01", "2020-02-01", 10.0, "c"), "turnover_jpy": 5e9},
        ]
    )
    out = simulate_diversified_portfolio(
        trades,
        initial_capital=1_000_000,
        max_positions=1,
        position_pct=1.0,
        entry_priority="sector_turnover",
        min_turnover_jpy=5e8,
    )
    assert out["skipped_turnover"] == 1
    assert out["accepted_trades"] == 1
    assert round(out["total_return_pct"], 6) == 10.0


def test_breadth_filter_keeps_only_crowded_days():
    from signalforge.portfolio.entry_features import attach_breadth

    rows = []
    days = pd.bdate_range("2020-01-01", periods=80)
    for i, d in enumerate(days):
        n = 8 if i == 79 else 1
        for k in range(n):
            rows.append(_trade(f"T{k}", str(d.date()), str((d + pd.Timedelta(days=3)).date()), 1.0, f"s{k}"))
    pool = attach_breadth(pd.DataFrame(rows), window=250, min_history=60)
    last = pool[pd.to_datetime(pool["entry_time"]) == days[-1]]
    assert (last["breadth_rank"] == 1.0).all()
    out = simulate_diversified_portfolio(
        pool,
        initial_capital=1_000_000,
        max_positions=5,
        position_pct=0.2,
        entry_priority="sector_random",
        min_breadth_rank=0.8,
    )
    assert out["accepted_trades"] == 5
    assert out["skipped_breadth"] == len(pool) - 8


def test_paper_book_upgrades_legacy_rules(tmp_path, monkeypatch):
    import json

    from signalforge.lab.portfolio_sim import DEFAULT_ENTRY_RULES
    from signalforge.paper import diversified as pd_mod

    monkeypatch.setattr(pd_mod, "data_dir", lambda: tmp_path)
    path = pd_mod.diversified_book_path("swing", "x")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"style": "swing", "strategy": "x", "entry_priority": "sector_liquidity"}))
    book = pd_mod.DiversifiedPaperBook.load("swing", "x")
    assert book is not None
    assert book.entry_rules() == DEFAULT_ENTRY_RULES
    assert book.rules_version == pd_mod.ENTRY_RULES_VERSION
