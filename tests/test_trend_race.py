"""選別案の比較。学習期間だけを見て、確認期間では選び直さない。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from signalforge.research.trend_screen.chart import ChartMetrics
from signalforge.research.trend_screen.fund_asof import growth_ok
from signalforge.research.trend_screen.fundamentals import AnnualPoint
from signalforge.research.trend_screen.horse import (
    MonthRow,
    VariantResult,
    WindowStats,
    _simulate,
    _window,
    build_snapshots,
    choose_winner,
    is_confirmed,
    regime_flags,
    verdict_text,
)
from signalforge.research.trend_screen.variants import (
    catalog,
    passes_entry,
    select_chart_top5,
    select_primary,
    select_smooth,
)


def _book_row(**overrides: object) -> ChartMetrics:
    metrics = ChartMetrics(
        reliable_daily=True,
        ret_1y=0.2,
        ret_3y=0.8,
        excess_1y=0.1,
        excess_3y=0.2,
        ma200_slope=0.05,
        ma75_slope=0.03,
        mdd_1y=-0.08,
        mdd_3y=-0.12,
        pct_above_ma200=0.8,
        up_month_ratio=0.7,
        timing="ppp",
    )
    metrics.primary = {
        "price_above_ma200": True,
        "ma200_rising_60": True,
        "ma75_rising": True,
        "ret_1y_positive": True,
        "ret_3y_positive": True,
        "topix_excess_1y": True,
    }
    metrics.prefer = {"mdd_3y_within_35": True, "above_ma200_70": True}
    for key, value in overrides.items():
        setattr(metrics, key, value)
    return metrics


def test_catalog_is_twelve_fixed_variants() -> None:
    ids = [item.id for item in catalog()]
    assert len(ids) == 12
    assert len(set(ids)) == 12
    assert "gate_1y_uptrend" in ids
    assert "gate_1y_full" in ids


def test_entry_and_smooth_filters() -> None:
    calm = _book_row()
    pull = _book_row(timing="pullback_ma25")
    violent = _book_row(mdd_3y=-0.55, pct_above_ma200=0.4)
    violent.prefer = {"mdd_3y_within_35": False, "above_ma200_70": False}
    book = {"calm": calm, "pull": pull, "violent": violent}
    assert select_primary(book) == ["calm", "pull", "violent"]
    assert select_smooth(book) == ["calm", "pull"]
    assert passes_entry(calm, "ppp")
    assert not passes_entry(calm, "pullback")
    assert passes_entry(pull, "pullback")
    assert select_chart_top5(book)[0] in {"calm", "pull"}


def test_winner_uses_train_cagr_only() -> None:
    high_cagr = VariantResult(
        "a",
        "高CAGR",
        "",
        WindowStats(cagr=0.12, mean_excess=0.001, max_dd=-0.30, n_invested=20),
        WindowStats(cagr=-0.05, mean_excess=-0.01, max_dd=-0.10, n_invested=20),
    )
    high_excess = VariantResult(
        "b",
        "高超過",
        "",
        WindowStats(cagr=0.08, mean_excess=0.01, max_dd=-0.05, n_invested=20),
        WindowStats(cagr=0.10, mean_excess=0.02, max_dd=-0.05, n_invested=20),
    )
    chosen = choose_winner([high_cagr, high_excess])
    assert chosen is not None and chosen.id == "a"
    assert is_confirmed(chosen) is False
    assert "見送り" in verdict_text(chosen, False)


def test_regime_flags_need_history() -> None:
    index = pd.bdate_range("2020-01-01", periods=300)
    bench = pd.Series(range(100, 400), index=index, dtype=float)
    day = index[-1]
    flags = regime_flags(bench, day)
    assert flags["above200"] is True
    assert flags["uptrend"] is True
    short = bench.iloc[:50]
    assert regime_flags(short, short.index[-1])["above200"] is None


def test_fund_growth_waits_ninety_days() -> None:
    annuals = [
        AnnualPoint("2020-03-31", sales=100, operating_income=10, eps=1),
        AnnualPoint("2021-03-31", sales=120, operating_income=12, eps=1.2),
        AnnualPoint("2022-03-31", sales=140, operating_income=14, eps=1.4),
    ]
    assert growth_ok(annuals, date(2022, 6, 28)) is None
    assert growth_ok(annuals, date(2022, 6, 29)) is True
    declining = [
        AnnualPoint("2020-03-31", sales=100, operating_income=10, eps=1),
        AnnualPoint("2021-03-31", sales=120, operating_income=12, eps=1.2),
        AnnualPoint("2022-03-31", sales=110, operating_income=14, eps=1.4),
    ]
    assert growth_ok(declining, date(2022, 12, 31)) is False


def test_flat_month_pays_the_entry_cost() -> None:
    index = pd.bdate_range("2024-01-01", periods=70)
    close = pd.Series(100.0, index=index)
    bench = pd.Series(100.0, index=index)
    january = pd.Timestamp(index[index.month == 1][-1])
    february = pd.Timestamp(index[index.month == 2][-1])
    snaps = [(january, {"A": _book_row()}), (february, {"A": _book_row()})]
    variant = next(item for item in catalog() if item.id == "gate_1y")
    result = _simulate(variant, snaps, {"A": close}, bench, january, {})
    assert len(result.months) == 1
    assert result.months[0].gross == 0
    assert result.months[0].cost == 0.001


def test_future_prices_do_not_change_an_earlier_signal() -> None:
    long_index = pd.bdate_range("2018-01-01", periods=860)
    steps = range(len(long_index))
    steady = pd.Series([100 * (1.0004 ** step) for step in steps], index=long_index)
    slow = pd.Series([100 * (1.0001 ** step) for step in steps], index=long_index)
    volume = pd.Series(1_000_000.0, index=long_index)
    before, _bench = build_snapshots({"A": steady}, {"A": volume}, slow)
    cut = long_index[780]
    broken = steady.copy()
    broken.loc[broken.index > cut] = 10.0
    after, _bench2 = build_snapshots({"A": broken}, {"A": volume}, slow)
    compared = 0
    for (day, left), (_day, right) in zip(before, after):
        if day > cut or "A" not in left:
            continue
        assert left["A"].price == right["A"].price
        assert left["A"].ret_3y == right["A"].ret_3y
        compared += 1
    assert compared > 12


def test_cash_months_count_in_the_average() -> None:
    stats = _window(
        [
            MonthRow("x", "2021-01-29", 0, 0.0, 0.0, 0.0, 0.02, -0.02, ""),
            MonthRow("x", "2021-02-26", 1, 0.03, 0.001, 0.029, 0.01, 0.019, "A"),
        ]
    )
    assert stats.mean_excess == (-0.02 + 0.019) / 2
    assert stats.n_invested == 1
