"""月末判定と毎日判定。CAGRの年率化を頻度ごとに分ける。"""

from __future__ import annotations

import pandas as pd

from signalforge.research.trend_screen.frequency import (
    _window_freq,
    choose_freq_winner,
    daily_signals,
    monthly_signals,
    primary_mask,
    specs,
)
from signalforge.research.trend_screen.horse import MonthRow, VariantResult, WindowStats


def test_specs_are_fixed_to_two() -> None:
    assert [item.id for item in specs()] == ["primary_monthly", "primary_daily"]


def test_primary_mask_needs_three_years() -> None:
    index = pd.bdate_range("2018-01-01", periods=900)
    close = pd.Series([100 * (1.0005 ** i) for i in range(900)], index=index)
    bench = pd.Series([100 * (1.0002 ** i) for i in range(900)], index=index)
    mask = primary_mask(close, bench)
    assert not bool(mask.iloc[500])
    assert bool(mask.iloc[-1])


def test_daily_has_more_signals_than_monthly() -> None:
    index = pd.bdate_range("2020-01-01", periods=400)
    bench = pd.Series(range(400), index=index, dtype=float)
    ready = pd.Timestamp(index[100])
    assert len(daily_signals(bench, ready)) > len(monthly_signals(bench, ready))


def test_cagr_annualization_differs_by_frequency() -> None:
    rows = [MonthRow("x", "2021-01-04", 1, 0.01, 0.0, 0.01, 0.0, 0.01, "A") for _ in range(12)]
    monthly = _window_freq(rows, periods_per_year=12)
    daily_like = _window_freq(rows, periods_per_year=245)
    assert monthly.cagr is not None and daily_like.cagr is not None
    assert daily_like.cagr > monthly.cagr


def test_daily_needs_more_invested_days_to_win() -> None:
    monthly = VariantResult(
        "primary_monthly",
        "月末",
        "",
        WindowStats(cagr=0.10, mean_excess=0.01, max_dd=-0.1, n_invested=20),
        WindowStats(cagr=0.10, mean_excess=0.01, max_dd=-0.1, n_invested=20),
    )
    daily = VariantResult(
        "primary_daily",
        "毎日",
        "",
        WindowStats(cagr=0.20, mean_excess=0.01, max_dd=-0.1, n_invested=100),
        WindowStats(cagr=0.20, mean_excess=0.01, max_dd=-0.1, n_invested=100),
    )
    by_id = {item.id: item for item in specs()}
    assert choose_freq_winner([monthly, daily], by_id).id == "primary_monthly"
