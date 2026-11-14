"""ライブの月末シグナルは、月中の最終バーを使わない。"""

from __future__ import annotations

import pandas as pd
import pytest

from signalforge.research.trend_screen.system import _is_month_end_session, latest_signal_day


def test_mid_month_uses_previous_month_end() -> None:
    index = pd.bdate_range("2024-09-01", "2024-11-13")
    bench = pd.Series(1.0, index=index)
    signal = latest_signal_day(bench)
    assert signal.month == 10
    assert signal == pd.Timestamp(index[index.month == 10][-1])


def test_true_month_end_session_is_usable() -> None:
    # 2024-11-29 is the last weekday of November 2024
    index = pd.bdate_range("2024-09-01", "2024-11-29")
    bench = pd.Series(1.0, index=index)
    assert _is_month_end_session(index[-1])
    signal = latest_signal_day(bench)
    assert signal.month == 11


def test_month_end_helper() -> None:
    assert _is_month_end_session(pd.Timestamp("2024-11-29"))
    assert not _is_month_end_session(pd.Timestamp("2024-11-13"))
