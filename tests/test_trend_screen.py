"""長期上昇トレンドの採点。ネットワークは使わない。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from signalforge.research.trend_screen.chart import ChartMetrics, evaluate_chart, max_drawdown
from signalforge.research.trend_screen.config import CHART_MAX, FUND_MAX, HISTORICAL_VALUATION_MAX, VALUATION_MAX
from signalforge.research.trend_screen.forward import chart_forward
from signalforge.research.trend_screen.fundamentals import AnnualPoint, score_fundamentals
from signalforge.research.trend_screen.report import write_outputs
from signalforge.research.trend_screen.score import assemble, grade, ranked, score_chart
from signalforge.research.trend_screen.screen import ScreenUsageError, _parse_tickers, evaluate_name
from signalforge.research.trend_screen.statements import annuals_from_frames
from signalforge.research.trend_screen.universe import is_common_code
from signalforge.research.trend_screen.valuation import score_valuation


def test_weights_sum_to_the_hypothesis() -> None:
    assert sum(CHART_MAX.values()) == 50
    assert sum(FUND_MAX.values()) == 35
    assert VALUATION_MAX == 15
    assert HISTORICAL_VALUATION_MAX == 12


def test_common_share_codes() -> None:
    assert is_common_code("2702")
    assert is_common_code("2702.T")
    assert is_common_code("285A")
    assert not is_common_code("25935")
    assert not is_common_code("130A0")


def test_close_drawdown_uses_the_peak() -> None:
    px = pd.Series([100.0, 110.0, 90.0, 120.0])
    assert max_drawdown(px) == pytest.approx(90 / 110 - 1)


def _full_chart(**overrides: object) -> ChartMetrics:
    metrics = ChartMetrics(
        reliable_daily=True,
        as_of="2026-11-13",
        bars=1200,
        price=2000.0,
        ma5=1980.0,
        ma25=1900.0,
        ma75=1700.0,
        ma200=1500.0,
        ma5_slope=0.02,
        ma25_slope=0.02,
        ma75_slope=0.05,
        ma200_slope=0.10,
        ret_1y=0.40,
        ret_3y=2.0,
        excess_1y=0.20,
        mdd_1y=-0.05,
        mdd_3y=-0.05,
        pct_above_ma200=0.90,
        dd_52w=-0.04,
        vol_1y=0.22,
        up_month_ratio=0.70,
        turnover_20d=100_000_000.0,
        timing="ppp",
        ret_3y_start="2023-11-01",
    )
    for key, value in overrides.items():
        setattr(metrics, key, value)
    metrics.primary = {
        "price_above_ma200": None if metrics.price is None or metrics.ma200 is None else metrics.price > metrics.ma200,
        "ma200_rising_60": None if metrics.ma200_slope is None else metrics.ma200_slope > 0,
        "ma75_rising": None if metrics.ma75_slope is None else metrics.ma75_slope > 0,
        "ret_1y_positive": None if metrics.ret_1y is None else metrics.ret_1y > 0,
        "ret_3y_positive": None if metrics.ret_3y is None else metrics.ret_3y > 0,
        "topix_excess_1y": None if metrics.excess_1y is None else metrics.excess_1y > 0,
    }
    metrics.prefer = {
        "mdd_3y_within_35": None if metrics.mdd_3y is None else metrics.mdd_3y >= -0.35,
        "mdd_1y_within_25": None if metrics.mdd_1y is None else metrics.mdd_1y >= -0.25,
        "above_ma200_70": None if metrics.pct_above_ma200 is None else metrics.pct_above_ma200 >= 0.70,
        "within_20_of_52w": None if metrics.dd_52w is None else metrics.dd_52w >= -0.20,
        "liquid": None if metrics.turnover_20d is None else metrics.turnover_20d >= 50_000_000,
    }
    return metrics


def test_smooth_chart_can_score_fifty_and_a_deep_drawdown_is_penalized() -> None:
    smooth = score_chart(_full_chart())
    assert smooth.score == pytest.approx(50)
    anchors = {0.0: 10.0, -0.15: 10.0, -0.35: 5.0, -0.50: 2.0, -0.70: 0.0, -0.80: 0.0}
    for drawdown, points in anchors.items():
        scored = score_chart(_full_chart(mdd_3y=drawdown))
        assert scored.components["mdd_3y"] == pytest.approx(points)
    boom = score_chart(_full_chart(ret_3y=2.0, mdd_3y=-0.55))
    steadier = score_chart(_full_chart(ret_3y=1.0, mdd_3y=-0.10))
    assert boom.components["ret_3y"] > steadier.components["ret_3y"]
    assert steadier.score > boom.score


def test_missing_topix_is_not_scored_as_zero_and_one_miss_keeps_a_score() -> None:
    missing = score_chart(_full_chart(excess_1y=None))
    assert missing.score == pytest.approx(46)
    assert missing.max_points == 46
    weak_year = score_chart(_full_chart(ret_1y=-0.05))
    assert weak_year.score is not None
    assert weak_year.components["ret_1y"] == 0


def test_weekly_bars_are_not_scored() -> None:
    index = pd.date_range("2020-01-05", periods=200, freq="W")
    close = pd.Series(np.linspace(100, 200, len(index)), index=index)
    metrics = evaluate_chart(close, pd.Series(1_000_000, index=index))
    assert metrics.reliable_daily is False
    assert score_chart(metrics).score is None


def _daily(periods: int = 1000, growth: float = 0.0005, start: float = 100.0):
    index = pd.bdate_range("2020-01-01", periods=periods)
    close = pd.Series(start * (1 + growth) ** np.arange(periods), index=index)
    bench = pd.Series(start * (1.0002) ** np.arange(periods), index=index)
    volume = pd.Series(1_000_000.0, index=index)
    return close, bench, volume


def test_daily_uptrend_is_ppp_and_a_crash_is_measured_from_closes() -> None:
    close, bench, volume = _daily()
    metrics = evaluate_chart(close, volume, None, bench)
    assert metrics.timing == "ppp"
    assert all(metrics.primary[key] is True for key in metrics.primary)
    assert metrics.mdd_3y == pytest.approx(0)
    assert metrics.ret_3y is not None and metrics.ret_3y > 0

    index = close.index[:900]
    crashed = pd.Series(100.0, index=index)
    crashed.iloc[:400] = np.linspace(100, 300, 400)
    crashed.iloc[400:460] = np.linspace(300, 140, 60)
    crashed.iloc[460:] = np.linspace(140, 280, 440)
    crash = evaluate_chart(crashed, volume.reindex(index), None, bench.reindex(index))
    assert crash.mdd_3y is not None and crash.mdd_3y <= -0.50
    assert score_chart(crash).components["mdd_3y"] <= 2.1


def test_downtrend_is_removed_from_candidates() -> None:
    close, bench, volume = _daily(growth=-0.0008, start=300)
    metrics = evaluate_chart(close, volume, None, bench)
    assert metrics.timing == "ma200_down"
    row = assemble(
        code="9999.T",
        name="下降",
        market="未確認",
        sector="情報・通信業",
        market_cap=None,
        metrics=metrics,
        fund=score_fundamentals([], "情報・通信業", source="test"),
        val=score_valuation(price=metrics.price, annuals=[], source="test"),
        price_source="test",
        in_listing=True,
    )
    assert row.candidate_status == "原則除外"
    assert "200日線が下向き" in row.flags
    assert ranked([row]) == []


def _years(eps: list[float], sales: list[float] | None = None, op: list[float] | None = None) -> list[AnnualPoint]:
    sales_row = sales or [100.0, 120.0, 140.0, 160.0]
    op_row = op or [10.0, 12.0, 14.0, 16.0]
    days = ["2021-03-31", "2022-03-31", "2023-03-31", "2024-03-31"]
    return [
        AnnualPoint(
            fiscal_end=day,
            sales=sales_row[i],
            operating_income=op_row[i],
            eps=eps[i],
            net_income=180.0,
            operating_cf=20.0,
            equity=1000.0,
            assets=2000.0,
        )
        for i, day in enumerate(days)
    ]


def test_fundamentals_sector_and_penalty() -> None:
    annuals = _years([10, 12, 14, 16])
    full = score_fundamentals(annuals, "情報・通信業", source="test")
    assert full.score == pytest.approx(35)
    bank = score_fundamentals(annuals, "銀行業", source="test")
    assert bank.components["equity"] == 2
    assert any("一律基準" in note for note in bank.notes)
    unknown = score_fundamentals(annuals, None, source="test")
    assert unknown.components["equity"] is None
    assert unknown.max_points == 32
    surged = _years([10, 12, 14, 16], sales=[100, 120, 140, 145], op=[10, 12, 14, 20])
    penalized = score_fundamentals(surged, "小売業", source="test")
    assert any("急増" in item for item in penalized.penalties)
    assert penalized.score < full.score


def test_peg_separates_forecast_history_and_missing() -> None:
    years = (date(2024, 3, 31) - date(2021, 3, 31)).days / 365.25
    end = 100 * (1.12 ** years)
    annuals = _years([100, 112, 125, end])
    price = 15 * end
    historical = score_valuation(price=price, annuals=annuals, source="yfinance")
    assert historical.status == "過去PEG"
    assert historical.per == pytest.approx(15)
    assert historical.growth_pct == pytest.approx(12)
    assert historical.peg == pytest.approx(15 / 12)
    assert historical.score == pytest.approx(12)
    assert "予想PEGではない" in historical.formula

    forecast = score_valuation(
        price=price,
        annuals=annuals,
        forecast_per=18,
        forecast_growth_pct=12,
        forecast_horizon_years=3,
        forecast_source="アナリスト",
        source="yfinance",
    )
    assert forecast.status == "予想PEG"
    assert forecast.peg == pytest.approx(1.5)
    assert forecast.score == pytest.approx(15)
    assert "予想PER 18.00" in forecast.formula

    single = score_valuation(
        price=price,
        annuals=annuals,
        forecast_per=10,
        forecast_growth_pct=40,
        forecast_horizon_years=1,
        forecast_source="今期",
        source="yfinance",
    )
    assert single.status == "過去PEG"
    assert any("使っていない" in note for note in single.notes)

    declining = score_valuation(price=150, annuals=_years([40, 30, 20, 10]), source="test")
    assert declining.status == "算出不能"
    assert declining.peg is None
    assert declining.score == 0

    missing = score_valuation(price=150, annuals=[], source="test")
    assert missing.status == "未確認"
    assert missing.score is None


def test_same_numbers_score_the_same_for_any_code() -> None:
    close, bench, volume = _daily()
    annuals = _years([10, 12, 14, 16])
    bars = pd.DataFrame({"close": close, "volume": volume})
    kwargs = dict(
        market="プライム",
        sector="小売業",
        market_cap=None,
        bars=bars,
        annuals=annuals,
        benchmark=bench,
        price_source="test",
        fundamental_source="test",
        in_listing=True,
    )
    left = evaluate_name(code="2702.T", name="左", **kwargs)
    right = evaluate_name(code="3563.T", name="右", **kwargs)
    assert left.total == right.total
    assert left.total is not None
    assert left.candidate_status == "選定対象"
    root = Path(__file__).resolve().parents[1] / "src" / "signalforge" / "research" / "trend_screen"
    scored = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in ("score.py", "chart.py", "fundamentals.py", "valuation.py")
    )
    assert "2702" not in scored
    assert "3563" not in scored


def test_grade_thresholds_and_illiquid_name_stays_selectable() -> None:
    assert grade(85, True) == "最優先候補"
    assert grade(84.9, True) == "有力候補"
    assert grade(75, True) == "有力候補"
    assert grade(74.9, True) == "監視候補"
    assert grade(65, True) == "監視候補"
    assert grade(64.9, True) == "原則見送り"
    assert "除外" in grade(90, False)
    thin = _full_chart(turnover_20d=1_000_000)
    fund = score_fundamentals(_years([10, 12, 14, 16]), "小売業", source="test")
    valuation = score_valuation(price=2000, annuals=fund.annuals, source="test")
    row = assemble(
        code="1111.T",
        name="薄い",
        market="グロース",
        sector="小売業",
        market_cap=None,
        metrics=thin,
        fund=fund,
        val=valuation,
        price_source="test",
        in_listing=True,
    )
    assert "流動性が不足" in row.flags
    assert row.candidate_status == "選定対象"


def test_statements_read_items_as_rows() -> None:
    columns = pd.to_datetime(["2022-03-31", "2023-03-31", "2024-03-31"])
    income = pd.DataFrame(
        [[100, 120, 150], [10, 14, 20], [5, 6, 8], [8, 9, 12]],
        index=["Total Revenue", "Operating Income", "Diluted EPS", "Net Income"],
        columns=columns,
    )
    balance = pd.DataFrame(
        [[50, 60, 70], [100, 110, 120]],
        index=["Stockholders Equity", "Total Assets"],
        columns=columns,
    )
    cash = pd.DataFrame([[7, 8, 9]], index=["Operating Cash Flow"], columns=columns)
    annuals = annuals_from_frames(income, balance, cash)
    assert [row.sales for row in annuals] == [100, 120, 150]
    assert annuals[-1].eps == 8
    assert annuals[-1].equity_ratio == pytest.approx(70 / 120)
    flipped = annuals_from_frames(income.T, balance, cash)
    assert [row.sales for row in flipped] == [100, 120, 150]


def test_forward_return_is_the_next_close_and_ignores_later_prices() -> None:
    index = pd.bdate_range("2018-01-01", periods=1400)
    growth = 0.0008
    close = pd.Series(100 * (1 + growth) ** np.arange(1400), index=index)
    bench = pd.Series(100 * (1.0002) ** np.arange(1400), index=index)
    volume = pd.Series(1_000_000.0, index=index)
    report = chart_forward({"A": close}, {"A": volume}, bench)
    horizon = next(item for item in report.horizons if item.horizon == 21)
    assert horizon.n > 10
    assert horizon.mean_gross == pytest.approx((1 + growth) ** 21 - 1, rel=1e-6)
    assert horizon.mean_net == pytest.approx(horizon.mean_gross - 0.002)
    assert "生存者バイアス" in report.note
    assert "未実施" in report.note

    cut = index[900]
    changed = close.copy()
    changed.loc[changed.index > cut] = 1.0
    after = chart_forward({"A": changed}, {"A": volume}, bench)
    limit = cut.date().isoformat()
    before = [day for day in report.signal_dates if day <= limit]
    assert before
    assert before == [day for day in after.signal_dates if day <= limit]


def test_report_does_not_claim_a_full_market_screen(tmp_path: Path) -> None:
    annuals = _years([10, 12, 14, 16])
    row = assemble(
        code="2702.T",
        name="日本マクドナルドホールディングス",
        market="プライム（内国株式）",
        sector="小売業",
        market_cap=None,
        metrics=_full_chart(),
        fund=score_fundamentals(annuals, "小売業", source="test"),
        val=score_valuation(price=200, annuals=annuals, source="test"),
        price_source="test",
        in_listing=True,
    )
    write_outputs(
        [row],
        out=tmp_path,
        meta={
            "method_version": "1.0",
            "run_at": "2026-11-13T12:00:00",
            "as_of": "2026-11-13",
            "price_source": "test",
            "benchmark": "test",
            "listing_as_of": "test",
            "listing_source": "test",
            "universe_note": "日足を取得してスクリーニングした件数ではない。",
        },
        bars={},
        forward=None,
    )
    text = (tmp_path / "ranking.md").read_text(encoding="utf-8")
    assert "全市場" in text
    assert "仮説" in text
    assert "2702" in text
    assert "特別利益" in text


def test_cli_refuses_to_imply_a_full_scan() -> None:
    with pytest.raises(ScreenUsageError):
        _parse_tickers("", False)
