from datetime import date

import pandas as pd

from signalforge.experiments.series import (
    pack_equity_daily,
    pack_trades,
    period_sliceable,
    slice_row_metrics,
    ticker_row_has_series,
)


def test_pack_and_slice_row_metrics():
    idx = pd.date_range("2023-01-01", periods=5, freq="D")
    equity = pd.Series([100.0, 101.0, 99.0, 102.0, 103.0], index=idx)
    trades = pd.DataFrame(
        [
            {
                "entry_time": idx[0],
                "exit_time": idx[1],
                "pnl_pct": 1.0,
                "gross_pnl_pct": 1.1,
                "hold_bars": 1,
            },
            {
                "entry_time": idx[2],
                "exit_time": idx[3],
                "pnl_pct": -0.5,
                "gross_pnl_pct": -0.4,
                "hold_bars": 1,
            },
        ]
    )
    row = {
        "ticker": "9999.T",
        "trades_compact": pack_trades(trades),
        "equity_daily": pack_equity_daily(equity),
    }
    assert ticker_row_has_series(row)
    m = slice_row_metrics(row, date(2023, 1, 2), date(2023, 1, 3))
    assert m is not None
    assert m["total_trades"] == 1
    assert m["avg_pnl_pct"] == 1.0


def test_period_sliceable_bounds():
    assert period_sliceable(date(2023, 1, 1), None, date(2020, 1, 1), None)
    assert not period_sliceable(date(2019, 1, 1), None, date(2020, 1, 1), None)
    assert not period_sliceable(
        date(2023, 1, 1),
        date(2025, 1, 1),
        date(2020, 1, 1),
        date(2024, 1, 1),
    )
