"""Paper equity snapshots may mix tz-aware and naive bar timestamps (5m vs 1d)."""

from __future__ import annotations

import pandas as pd

from signalforge.report.static_dashboard import _paper_summary


class _FakePortfolio:
    closed_trades: list = []
    equity_snapshots = [
        {"date": "2024-01-02 09:00:00+00:00", "equity": 100_000.0},
        {"date": "2024-01-03", "equity": 101_000.0},
    ]
    initial_cash = 100_000.0

    def mark_to_market_equity(self, _last_close: float) -> float:
        return 101_000.0


def test_paper_summary_mixed_tz_snapshots():
    df = pd.DataFrame({"close": [100.0]}, index=pd.date_range("2024-01-03", periods=1, tz="UTC"))
    summary = _paper_summary(_FakePortfolio(), df)
    assert len(summary["eq"]) == 2
    assert summary["eq"].index.tz is not None
