"""Point-in-time rules for the earnings-surprise study. No network."""

from __future__ import annotations

from datetime import date, timedelta

from signalforge.research.earnings_surprise.config import BENCHMARK_CODE
from signalforge.research.earnings_surprise.events import build_events, compare_forecast
from signalforge.research.earnings_surprise.features import build_candidates
from signalforge.research.earnings_surprise.metrics import find_book, is_headline
from signalforge.research.earnings_surprise.panel import Listing, MasterBook, Panel, Series, entry_timing
from signalforge.research.earnings_surprise.simulate import build_books, simulate


def _days(n: int = 70) -> list[date]:
    return [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]


def _bar(day: date, price: float, *, open_: float | None = None, high: float | None = None, low: float | None = None, va: float = 1_000_000_000) -> dict:
    opened = price if open_ is None else open_
    return {
        "Date": day.isoformat(),
        "O": opened,
        "H": price if high is None else high,
        "L": price if low is None else low,
        "C": price,
        "Vo": 1000,
        "Va": va,
        "AdjO": opened,
        "AdjH": price if high is None else high,
        "AdjL": price if low is None else low,
        "AdjC": price,
    }


def _listing(code: str, name: str = "") -> Listing:
    return Listing(code, name or code, "0111", "011", "輸送用機器", "TOPIX Large70")


def _book(days: list[date], codes: list[str]) -> MasterBook:
    return MasterBook([(days[0], {code: _listing(code) for code in codes})])


def _panel(days: list[date], series: dict[str, Series]) -> Panel:
    return Panel(days, series, BENCHMARK_CODE)


def _flat_series(code: str, days: list[date], price: float = 1000) -> Series:
    return Series.from_rows(code, [_bar(day, price) for day in days])


def test_timing_does_not_use_the_announcement_close() -> None:
    days = _days(5)
    intraday = entry_timing(days, days[2], "14:00:00")
    after = entry_timing(days, days[2], "16:30:00")
    before = entry_timing(days, days[2], "08:30:00")
    missing = entry_timing(days, days[2], "")
    assert intraday is not None and intraday.pre_date == days[1] and intraday.entry_date == days[3]
    assert after is not None and after.pre_date == days[2] and after.entry_date == days[3]
    assert before is not None and before.pre_date == days[1] and before.entry_date == days[2]
    assert missing is not None and missing.pre_date == days[2]


def test_revision_unit_break_is_not_a_consensus_beat() -> None:
    assert compare_forecast(10, 20_000) == (None, True)
    assert compare_forecast(20_000, 21_000) == (True, True)
    rows = [
        {"Code": "AAA", "DiscDate": "2024-05-01", "DiscTime": "15:30:00", "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurFYEn": "2025-03-31", "FOP": 10},
        {"Code": "AAA", "DiscDate": "2024-08-01", "DiscTime": "15:30:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurFYEn": "2025-03-31", "FOP": 20_000},
        {"Code": "AAA", "DiscDate": "2024-11-01", "DiscTime": "15:30:00", "DocType": "2QFinancialStatements_Consolidated_JP", "CurPerType": "2Q", "CurFYEn": "2025-03-31", "FOP": 21_000},
        {"Code": "AAA", "DiscDate": "2024-08-01", "DiscTime": "15:30:00", "DocType": "1QFinancialStatements_NonConsolidated_JP", "CurPerType": "1Q", "CurFYEn": "2025-03-31", "FOP": 99},
    ]
    events = build_events(rows)
    assert all(event.consensus_op is None and event.basis.startswith("company") for event in events)
    assert all("NonConsolidated" not in event.doc_type for event in events)
    by_day = {event.disc_date.isoformat(): event for event in events}
    assert by_day["2024-05-01"].rev_op is None and by_day["2024-05-01"].c0 is False
    assert by_day["2024-08-01"].rev_op is None
    assert by_day["2024-11-01"].rev_op is True and by_day["2024-11-01"].c0 is True


def test_yoy_margin_passes_without_a_forecast() -> None:
    rows = [
        {"Code": "AAA", "DiscDate": "2024-08-01", "DiscTime": "15:00:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurPerEn": "2024-06-30", "CurFYEn": "2025-03-31", "Sales": 100, "OP": 10},
        {"Code": "AAA", "DiscDate": "2025-08-01", "DiscTime": "15:00:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurPerEn": "2025-06-30", "CurFYEn": "2026-03-31", "Sales": 120, "OP": 15},
    ]
    events = build_events(rows)
    later = events[-1]
    assert later.rev_op is None
    assert later.op_yoy is not None and later.op_yoy > 0
    assert later.opm_delta is not None and later.opm_delta > 0
    assert later.c0 is True


def _world(days: list[date], names: list[str], prices: dict[str, list[float]] | None = None) -> tuple[Panel, MasterBook]:
    series = {BENCHMARK_CODE: _flat_series(BENCHMARK_CODE, days, 100)}
    for code in names:
        path = prices[code] if prices and code in prices else [1000.0] * len(days)
        series[code] = Series.from_rows(code, [_bar(day, price) for day, price in zip(days, path)])
    return _panel(days, series), _book(days, names)


def test_score_does_not_treat_missing_fields_as_full_marks() -> None:
    days = _days()
    panel, book = _world(days, ["AAA", "BBB", "CCC", "DDD", "EEE"])
    disc = days[30]
    rows = [
        {"Code": "AAA", "DiscDate": days[10].isoformat(), "DiscTime": "16:00:00", "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurFYEn": "2025-03-31", "FOP": 100},
        {"Code": "AAA", "DiscDate": disc.isoformat(), "DiscTime": "14:00:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurFYEn": "2025-03-31", "FOP": 120},
    ]
    candidates, _counts = build_candidates(build_events(rows), panel, book)
    chosen = [row for row in candidates if row.event.disc_date == disc]
    assert len(chosen) == 1
    assert chosen[0].event.c0 is True
    assert chosen[0].score < 25
    assert chosen[0].confidence != "高"
    assert "欠測" in chosen[0].score_note


def test_intraday_jump_is_not_used_as_relative_strength() -> None:
    days = _days()
    names = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    prices = {code: [1000.0] * len(days) for code in names}
    prices["AAA"][30] = 1500.0
    panel, book = _world(days, names, prices)
    # Rebuild AAA so the announcement-day close is the jump, while the next open stays there.
    aaa = []
    for index, day in enumerate(days):
        price = 1500.0 if index >= 30 else 1000.0
        aaa.append(_bar(day, price))
    panel.series["AAA"] = Series.from_rows("AAA", aaa)
    disc = days[30]
    rows = [
        {"Code": "AAA", "DiscDate": days[10].isoformat(), "DiscTime": "16:00:00", "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurFYEn": "2025-03-31", "FOP": 100},
        {"Code": "AAA", "DiscDate": disc.isoformat(), "DiscTime": "14:00:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurFYEn": "2025-03-31", "FOP": 120},
    ]
    candidates, _counts = build_candidates(build_events(rows), panel, book)
    chosen = next(row for row in candidates if row.event.disc_date == disc)
    assert chosen.pre_date == days[29]
    assert chosen.entry_date == days[31]
    assert chosen.stock_ret_20 is not None and abs(chosen.stock_ret_20) < 1e-12
    assert chosen.c2 is False
    assert chosen.c3 is False


def test_stop_gap_and_same_day_stop() -> None:
    days = _days()
    names = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    panel, book = _world(days, names)
    gap_rows = []
    for index, day in enumerate(days):
        if index == 32:
            gap_rows.append(_bar(day, 905, open_=900, high=910, low=890))
        else:
            gap_rows.append(_bar(day, 1000))
    panel.series["AAA"] = Series.from_rows("AAA", gap_rows)
    stop_rows = []
    for index, day in enumerate(days):
        if index == 31:
            stop_rows.append(_bar(day, 1000, open_=1000, high=1000, low=940))
        else:
            stop_rows.append(_bar(day, 1000))
    panel.series["BBB"] = Series.from_rows("BBB", stop_rows)
    disc = days[30].isoformat()
    fins = []
    for code in ("AAA", "BBB"):
        fins.append({"Code": code, "DiscDate": days[10].isoformat(), "DiscTime": "16:00:00", "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurFYEn": "2025-03-31", "FOP": 100})
        fins.append({"Code": code, "DiscDate": disc, "DiscTime": "14:00:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurFYEn": "2025-03-31", "FOP": 120})
    candidates, _counts = build_candidates(build_events(fins), panel, book)
    trades, _excluded = simulate(candidates, panel)
    gap = next(trade for trade in trades if trade.code == "AAA" and is_headline(trade))
    stopped = next(trade for trade in trades if trade.code == "BBB" and is_headline(trade))
    assert gap.gap_loss is True
    assert abs(gap.exit_px - 900) < 1e-6
    assert stopped.stopped is True and stopped.gap_loss is False
    assert abs(stopped.exit_px - 950) < 1e-6
    assert stopped.exit_reason == "損切り"
    assert gap.ret < 900 / 1000 - 1


def test_method_c_lot_and_costs() -> None:
    days = _days()
    names = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    panel, book = _world(days, names)
    rows = []
    for index, day in enumerate(days):
        if index == 31:
            rows.append(_bar(day, 1000, open_=990, high=1010, low=990))
        else:
            rows.append(_bar(day, 1000))
    panel.series["AAA"] = Series.from_rows("AAA", rows)
    panel.series["BBB"] = Series.from_rows("BBB", [_bar(day, 20_000) for day in days])
    disc = days[30]
    fins = [
        {"Code": "AAA", "DiscDate": days[10].isoformat(), "DiscTime": "16:00:00", "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurFYEn": "2025-03-31", "FOP": 100},
        {"Code": "AAA", "DiscDate": disc.isoformat(), "DiscTime": "14:00:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurFYEn": "2025-03-31", "FOP": 120},
        {"Code": "BBB", "DiscDate": days[10].isoformat(), "DiscTime": "16:00:00", "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurFYEn": "2025-03-31", "FOP": 100},
        {"Code": "BBB", "DiscDate": disc.isoformat(), "DiscTime": "14:00:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurFYEn": "2025-03-31", "FOP": 120},
    ]
    candidates, _counts = build_candidates(build_events(fins), panel, book)
    trades, excluded = simulate(candidates, panel)
    method_c = [trade for trade in trades if trade.code == "AAA" and trade.method == "C" and trade.hold == 20 and abs(trade.stop + 0.05) < 1e-9]
    assert method_c and abs(method_c[0].entry_px - 1000) < 1e-6
    method_a = next(trade for trade in trades if trade.code == "AAA" and is_headline(trade))
    assert abs(method_a.entry_px - 990) < 1e-6
    assert any(row.code == "BBB" and row.reason == "単元未満" for row in excluded)
    unchanged = []
    for index, day in enumerate(days):
        high = 1000 if index == 31 else 1000
        unchanged.append(_bar(day, 1000, high=high))
    panel.series["AAA"] = Series.from_rows("AAA", unchanged)
    _trades, excluded_flat = simulate(build_candidates(build_events(fins), panel, book)[0], panel)
    assert any(row.code == "AAA" and row.method == "C" and row.reason == "高値未更新" for row in excluded_flat)
    flat = next(trade for trade in _trades if trade.code == "AAA" and is_headline(trade))
    assert flat.ret < 0


def test_sector_and_stock_strength_survive_a_flat_market() -> None:
    days = _days()
    names = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    prices = {code: [1000.0] * len(days) for code in names}
    prices["AAA"] = [1000.0 + index for index in range(len(days))]
    panel, book = _world(days, names, prices)
    disc = days[30]
    fins = [
        {"Code": "AAA", "DiscDate": days[10].isoformat(), "DiscTime": "16:00:00", "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurFYEn": "2025-03-31", "FOP": 100},
        {"Code": "AAA", "DiscDate": disc.isoformat(), "DiscTime": "16:00:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurFYEn": "2025-03-31", "FOP": 120},
    ]
    candidates, counts = build_candidates(build_events(fins), panel, book)
    chosen = next(row for row in candidates if row.event.disc_date == disc)
    assert counts["c0"] == 1
    assert chosen.c1 is True
    assert chosen.c2 is True
    assert chosen.c3 is True
    assert chosen.market_down is True


def test_account_skips_the_second_name_when_cash_is_short() -> None:
    days = _days()
    names = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    panel, book = _world(days, names)
    disc = days[30].isoformat()
    fins = []
    for code in ("AAA", "BBB"):
        fins.append({"Code": code, "DiscDate": days[10].isoformat(), "DiscTime": "16:00:00", "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurFYEn": "2025-03-31", "FOP": 100})
        fins.append({"Code": code, "DiscDate": disc, "DiscTime": "16:00:00", "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q", "CurFYEn": "2025-03-31", "FOP": 130})
    candidates, _counts = build_candidates(build_events(fins), panel, book)
    trades, _excluded = simulate(candidates, panel)
    books = build_books(trades, panel, account=1_500_000)
    account = find_book(books, "C0")
    assert account is not None
    assert len(account.funded_ids) == 1
    assert len(account.rejected_ids) == 1
    funded = next(trade for trade in trades if trade.id in account.funded_ids)
    assert funded.code == "AAA"
