"""Execution, ranking, and cost tests for the frozen STF rules."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from signalforge.research.stf.engine import Panel, simulate
from signalforge.research.stf.guidance import Disclosure, revision_map
from signalforge.research.stf.rules import StrategySpec
from signalforge.research.stf.signals import Snap, allocate, compute_indicators, rank_candidates


def _day(i: int) -> date:
    return date(2024, 1, 1) + timedelta(days=i)


def _snap(close: float, **overrides: float) -> Snap:
    fields = dict(
        adj_o=close,
        adj_c=close,
        ret20=0.05,
        ret60=0.08,
        sma25=close * 0.9,
        sma75=close * 0.8,
        sma25_lag5=close * 0.85,
        sma75_lag5=close * 0.75,
        adv20=100_000_000.0,
    )
    fields.update(overrides)
    return Snap(**fields)


def _panel(n: int, snaps: dict[date, dict[str, Snap]], month_ends: set[date], **kwargs: object) -> Panel:
    sessions = [_day(i) for i in range(n)]
    return Panel(
        sessions=sessions,
        snaps=snaps,
        universe={day: {"AAA": ("AAA", "電気機器")} for day in month_ends},
        month_ends=month_ends,
        benchmark={day: 100.0 for day in sessions},
        last_session={"AAA": sessions[-1]},
        last_close={"AAA": 100.0},
        **kwargs,  # type: ignore[arg-type]
    )


def _flat_snaps(n: int, close: float = 100.0) -> dict[date, dict[str, Snap]]:
    return {_day(i): {"AAA": _snap(close)} for i in range(n)}


def test_indicators_ignore_the_future() -> None:
    dates = [_day(i) for i in range(40)]
    base = pl.DataFrame(
        {
            "date": dates,
            "code": ["AAA"] * 40,
            "adj_c": [float(i + 1) for i in range(40)],
            "va": [100_000_000.0] * 40,
        }
    )
    shocked = base.with_columns(
        pl.when(pl.col("date") == dates[-1]).then(10_000.0).otherwise(pl.col("adj_c")).alias("adj_c")
    )
    left = compute_indicators(base)
    right = compute_indicators(shocked)
    shared = left.filter(pl.col("date") < dates[-1]).select(["date", "sma25", "ret20"])
    other = right.filter(pl.col("date") < dates[-1]).select(["date", "sma25", "ret20"])
    assert shared.equals(other)
    manual = sum(range(6, 31)) / 25.0  # closes 6..30 on the 30th row (index 29)
    got = left.filter(pl.col("date") == dates[29])["sma25"][0]
    assert got == manual


def test_rank_tie_break_is_deterministic() -> None:
    spec = StrategySpec("t", "score", 1.0, False, top_n=1, stop=None)
    low = _snap(100, ret20=0.04, ret60=0.06, adv20=80_000_000)
    high_adv = _snap(100, ret20=0.04, ret60=0.06, adv20=90_000_000)
    ranked = rank_candidates(
        [("BBB", low), ("AAA", high_adv)],
        0.0,
        0.0,
        spec,
    )
    assert ranked[0][0] == "AAA"
    same = rank_candidates([("BBB", low), ("AAA", low)], 0.0, 0.0, spec)
    assert same[0][0] == "AAA"


def test_score_weights_respect_the_ten_percent_cap() -> None:
    spec = StrategySpec("t", "score", 1.0, False, top_n=3, name_cap=0.10, stop=None)
    ranked = [("A", 10.0, 1.0, 1.0), ("B", 1.0, 1.0, 1.0), ("C", 1.0, 1.0, 1.0)]
    weights = allocate(ranked, spec)
    assert sum(item.weight for item in weights.values()) == pytest.approx(0.30)
    assert max(item.weight for item in weights.values()) == 0.10


def test_signal_fills_on_the_next_open_not_the_signal_close() -> None:
    n = 75
    snaps = _flat_snaps(n, 100.0)
    snaps[_day(71)]["AAA"] = _snap(100, adj_o=110.0, adj_c=130.0)
    panel = _panel(n, snaps, {_day(70)})
    spec = StrategySpec("A", "equal", 1.0, False, top_n=1, stop=None, fee=0.0, slippage=0.0, finance=0.0)
    result = simulate(panel, spec, 1_000_000)
    by_day = {row.day: row for row in result.daily}
    assert by_day[_day(70)].n_hold == 0
    assert by_day[_day(70)].equity == 1_000_000
    assert by_day[_day(71)].n_hold == 1
    # Sized off the prior close equity and filled at the next open (110), then marked at 130.
    assert by_day[_day(71)].equity == pytest.approx(1_000_000 / 110.0 * 130.0)


def test_stop_sells_on_the_following_open() -> None:
    n = 76
    snaps = _flat_snaps(n, 100.0)
    snaps[_day(72)]["AAA"] = _snap(90.0, sma25=97.0, sma75=80.0)
    panel = _panel(n, snaps, {_day(70)})
    spec = StrategySpec("C", "equal", 1.0, True, top_n=1, stop=-0.05, fee=0.0, slippage=0.0, finance=0.0)
    result = simulate(panel, spec, 1_000_000)
    by_day = {row.day: row for row in result.daily}
    assert by_day[_day(72)].n_hold == 1
    assert by_day[_day(73)].n_hold == 0
    assert result.exits.get("stop") == 1


def test_half_position_is_not_halved_again() -> None:
    n = 76
    snaps = _flat_snaps(n, 100.0)
    # Below the 25-day average, still above the 75-day average and the stop.
    weak = _snap(96.0, sma25=99.0, sma75=80.0, sma25_lag5=98.0, sma75_lag5=79.0)
    snaps[_day(72)]["AAA"] = weak
    snaps[_day(73)]["AAA"] = weak
    snaps[_day(74)]["AAA"] = weak
    panel = _panel(n, snaps, {_day(70)})
    spec = StrategySpec("C", "equal", 1.0, True, top_n=1, stop=-0.05, fee=0.0, slippage=0.0, finance=0.0)
    result = simulate(panel, spec, 1_000_000)
    by_day = {row.day: row for row in result.daily}
    assert by_day[_day(73)].gross / by_day[_day(73)].equity == 0.5
    assert by_day[_day(74)].gross / by_day[_day(74)].equity == 0.5
    assert result.exits.get("sma25_half") == 1


def test_costs_and_margin_interest() -> None:
    n = 73
    snaps = _flat_snaps(n, 100.0)
    sessions = [_day(i) for i in range(n)]
    sessions[-1] = sessions[-2] + timedelta(days=365)
    panel = Panel(
        sessions=sessions,
        snaps=snaps | {sessions[-1]: {"AAA": _snap(100.0)}},
        universe={sessions[70]: {"AAA": ("AAA", "その他")}},
        month_ends={sessions[70]},
        benchmark={day: 100.0 for day in sessions},
        last_session={"AAA": sessions[-1]},
        last_close={"AAA": 100.0},
    )
    # The snap dict is keyed by the original _day() dates. Point the last session at a copy.
    panel.snaps[sessions[-1]] = {"AAA": _snap(100.0)}
    spec = StrategySpec("E", "equal", 2.0, False, top_n=1, stop=None, fee=0.0, slippage=0.0, finance=0.02)
    result = simulate(panel, spec, 1_000_000)
    last = result.daily[-1]
    assert last.n_hold == 1
    assert round(result.interest) == 20_000
    assert round(last.equity) == 980_000


def test_round_trip_cost_reduces_equity() -> None:
    n = 73
    snaps = _flat_snaps(n, 100.0)
    panel = _panel(n, snaps, {_day(70)})
    spec = StrategySpec("A", "equal", 1.0, False, top_n=1, stop=None, fee=0.0015, slippage=0.0005, finance=0.0)
    result = simulate(panel, spec, 10_000)
    fill = next(row for row in result.daily if row.day == _day(71))
    assert fill.equity == 10_000 - 10_000 * 0.002


def test_delist_applies_extra_haircut() -> None:
    n = 73
    snaps = _flat_snaps(n, 100.0)
    panel = _panel(n, snaps, {_day(70)})
    panel.last_session["AAA"] = _day(71)
    panel.last_close["AAA"] = 100.0
    spec = StrategySpec("A", "equal", 1.0, False, top_n=1, stop=None, fee=0.0, slippage=0.0, finance=0.0)
    result = simulate(panel, spec, 10_000)
    assert result.delist_exits == 1
    assert result.daily[-1].equity == 9_900


def test_liquid_names_and_sector_cap_change_who_is_bought() -> None:
    spec = StrategySpec(
        "t",
        "equal",
        1.0,
        False,
        top_n=2,
        stop=None,
        min_adv=200_000_000,
        max_per_sector=1,
    )
    thin = _snap(100, adv20=80_000_000)
    electric_hi = _snap(1000, adv20=300_000_000, ret20=0.05, ret60=0.08)
    electric_lo = _snap(1000, adv20=300_000_000, ret20=0.02, ret60=0.03)
    chemical = _snap(1000, adv20=300_000_000, ret20=0.04, ret60=0.07)
    ranked = rank_candidates(
        [("LOW", thin), ("A", electric_lo), ("B", electric_hi), ("C", chemical)],
        0.0,
        0.0,
        spec,
        sectors={"A": "電気", "B": "電気", "C": "化学"},
    )
    codes = [row[0] for row in ranked]
    assert codes == ["B", "C"]


def test_regime_filter_stays_in_cash_when_benchmark_falls() -> None:
    n = 80
    snaps = _flat_snaps(n, 100.0)
    sessions = [_day(i) for i in range(n)]
    panel = Panel(
        sessions=sessions,
        snaps=snaps,
        universe={sessions[70]: {"AAA": ("AAA", "電気機器", "0111")}},
        month_ends={sessions[70]},
        benchmark={sessions[i]: 200.0 - i for i in range(n)},
        last_session={"AAA": sessions[-1]},
        last_close={"AAA": 100.0},
    )
    spec = StrategySpec(
        "G",
        "equal",
        1.0,
        False,
        top_n=1,
        stop=None,
        fee=0.0,
        slippage=0.0,
        finance=0.0,
        regime_sma=20,
    )
    result = simulate(panel, spec, 1_000_000)
    assert all(row.n_hold == 0 for row in result.daily)


def test_guidance_raise_is_invisible_before_the_announcement() -> None:
    sessions = [_day(i) for i in range(10)]
    rows = [
        Disclosure("AAA", _day(2), "12:00:00", "cons", "2026-03-31", 100.0),
        Disclosure("AAA", _day(4), "16:00:00", "cons", "2026-03-31", 120.0),
        Disclosure("BBB", _day(4), "12:00:00", "cons", "2026-03-31", 80.0),
        Disclosure("BBB", _day(3), "12:00:00", "cons", "2025-03-31", 50.0),
    ]
    asof_before = revision_map(rows, sessions, [_day(4)], lookback=63)
    assert asof_before[_day(4)] == {}
    asof_after = revision_map(rows, sessions, [_day(5)], lookback=63)
    assert asof_after[_day(5)]["AAA"] == "up"
    assert "BBB" not in asof_after[_day(5)]


def test_raise_only_and_drop_cut_use_the_revision_map() -> None:
    spec_only = StrategySpec("t", "equal", 1.0, False, top_n=2, stop=None, earnings_mode="raise_only")
    spec_cut = StrategySpec("t", "equal", 1.0, False, top_n=2, stop=None, earnings_mode="drop_cut")
    spec_first = StrategySpec("t", "equal", 1.0, False, top_n=2, stop=None, earnings_mode="raise_first")
    strong = _snap(1000, ret20=0.20, ret60=0.30)
    weak_raise = _snap(1000, ret20=0.02, ret60=0.03)
    cut = _snap(1000, ret20=0.10, ret60=0.12)
    rows = [("STRONG", strong), ("RAISE", weak_raise), ("CUT", cut)]
    revisions = {"RAISE": "up", "CUT": "down"}
    assert [row[0] for row in rank_candidates(rows, 0.0, 0.0, spec_only, revisions=revisions)] == ["RAISE"]
    assert [row[0] for row in rank_candidates(rows, 0.0, 0.0, spec_cut, revisions=revisions)] == ["STRONG", "RAISE"]
    assert [row[0] for row in rank_candidates(rows, 0.0, 0.0, spec_first, revisions=revisions)] == ["RAISE", "STRONG"]


def test_price_pnl_matches_equity_change_after_costs() -> None:
    n = 74
    snaps = _flat_snaps(n, 100.0)
    snaps[_day(72)]["AAA"] = _snap(110.0)
    panel = _panel(n, snaps, {_day(70)})
    spec = StrategySpec("A", "equal", 1.0, False, top_n=1, stop=None, fee=0.001, slippage=0.0, finance=0.0)
    result = simulate(panel, spec, 1_000_000)
    end = result.daily[-1].equity
    pnl = sum(result.pnl_by_code.values())
    assert end == pytest.approx(1_000_000 + pnl - result.costs - result.interest)
