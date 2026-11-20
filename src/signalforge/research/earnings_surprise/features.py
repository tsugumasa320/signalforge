"""Sector and stock relative strength, plus the provisional 100-point score.

Missing inputs add zero points. They are not treated as a perfect score.
The score does not decide entries. C0–C3 use the frozen boolean gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from signalforge.research.earnings_surprise.config import (
    BENCHMARK_CODE,
    COMMON_STOCK,
    MIN_SECTOR_MEMBERS,
    PRIME_MARKET,
)
from signalforge.research.earnings_surprise.events import Event
from signalforge.research.earnings_surprise.panel import Listing, MasterBook, Panel, Series, entry_timing


@dataclass
class Candidate:
    event: Event
    name: str
    sector: str
    scale: str
    entry_date: date
    pre_date: date
    stock_ret_5: float | None
    stock_ret_20: float | None
    bench_ret_5: float | None
    bench_ret_20: float | None
    sector_ret_5: float | None
    sector_ret_20: float | None
    sector_rs_5: float | None
    sector_rs_20: float | None
    stock_rs_bench_5: float | None
    stock_rs_bench_20: float | None
    stock_rs_sector_5: float | None
    stock_rs_sector_20: float | None
    above_ma25: bool | None
    vol_change: float | None
    pre_runup_20: float | None
    breadth: float | None
    turnover_ratio: float | None
    market_down: bool | None
    sector_above_ma: bool | None
    c1: bool
    c2: bool
    c3: bool
    score: float
    confidence: str
    score_note: str
    va: float


def _sub(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _positive(value: float | None) -> bool:
    return value is not None and value > 0.0


def _window_return(daily: dict[date, float | None], clock: list[date], day: date, n: int) -> float | None:
    try:
        index = clock.index(day)
    except ValueError:
        return None
    if index < n - 1:
        return None
    acc = 1.0
    for pos in range(index - n + 1, index + 1):
        value = daily.get(clock[pos])
        if value is None:
            return None
        acc *= 1.0 + value
    return acc - 1.0


def _above_ma(daily: dict[date, float | None], clock: list[date], day: date, n: int = 25) -> bool | None:
    try:
        index = clock.index(day)
    except ValueError:
        return None
    if index < n - 1:
        return None
    level = 1.0
    levels: list[float] = []
    start = index - n + 1
    # Build the level from the first return in the window only. The comparison
    # is whether the latest level sits above the mean of this window.
    for pos in range(start, index + 1):
        value = daily.get(clock[pos])
        if value is None:
            return None
        level *= 1.0 + value
        levels.append(level)
    if len(levels) < n:
        return None
    return levels[-1] > (sum(levels) / len(levels))


def sector_daily_returns(panel: Panel, book: MasterBook, min_members: int = MIN_SECTOR_MEMBERS) -> dict[str, dict[date, float | None]]:
    out: dict[str, dict[date, float | None]] = {}
    clock = panel.clock
    for index, day in enumerate(clock):
        if index == 0:
            continue
        listings = book.asof(clock[index - 1])
        grouped: dict[str, list[float]] = {}
        for code, listing in listings.items():
            if listing.mkt != PRIME_MARKET or listing.prod != COMMON_STOCK:
                continue
            series = panel.series.get(code)
            if series is None:
                continue
            ret = series.daily_ret(day)
            if ret is None:
                continue
            grouped.setdefault(listing.sector or "不明", []).append(ret)
        for sector, rets in grouped.items():
            bucket = out.setdefault(sector, {})
            bucket[day] = sum(rets) / len(rets) if len(rets) >= min_members else None
    return out


def market_daily(panel: Panel, book: MasterBook) -> dict[date, dict[str, float | None]]:
    stats: dict[date, dict[str, float | None]] = {}
    clock = panel.clock
    turnover: dict[date, float] = {}
    for index, day in enumerate(clock):
        listings = book.asof(clock[index - 1] if index else day)
        up = 0
        down = 0
        traded = 0.0
        for code, listing in listings.items():
            if listing.mkt != PRIME_MARKET or listing.prod != COMMON_STOCK:
                continue
            series = panel.series.get(code)
            if series is None:
                continue
            loc = series.at(day)
            if loc is not None:
                traded += series.va[loc]
            ret = series.daily_ret(day)
            if ret is None or ret == 0.0:
                continue
            if ret > 0.0:
                up += 1
            else:
                down += 1
        turnover[day] = traded
        breadth = up / (up + down) if (up + down) >= MIN_SECTOR_MEMBERS else None
        ratio: float | None = None
        if index >= 20:
            base = [turnover[clock[pos]] for pos in range(index - 20, index)]
            avg = sum(base) / len(base) if base else 0.0
            if avg > 0:
                ratio = traded / avg
        stats[day] = {"breadth": breadth, "turnover_ratio": ratio, "turnover": traded}
    return stats


def _add(points: float, observed: float, weight: float, flag: bool | None) -> tuple[float, float]:
    if flag is None:
        return points, observed
    observed += weight
    if flag:
        points += weight
    return points, observed


def score_candidate(row: Candidate) -> tuple[float, str, str]:
    points = 0.0
    observed = 0.0
    event = row.event
    points, observed = _add(points, observed, 5, event.rev_sales)
    points, observed = _add(points, observed, 8, event.rev_op)
    points, observed = _add(points, observed, 4, event.rev_eps if event.rev_eps is not None else event.rev_np)
    points, observed = _add(points, observed, 4, None if event.op_yoy is None else event.op_yoy > 0)
    points, observed = _add(points, observed, 2, None if event.opm_delta is None else event.opm_delta > 0)
    revisions = (event.rev_sales, event.rev_op, event.rev_np, event.rev_eps)
    if any(item is not None for item in revisions):
        observed += 2
        if any(item is True for item in revisions):
            points += 2
    # Persistence (20) is not in the summary feed: orders, recurring revenue,
    # new products, pricing, overseas mix, outlook quality, one-off items.
    points, observed = _add(points, observed, 5, None if row.sector_rs_5 is None else row.sector_rs_5 > 0)
    points, observed = _add(points, observed, 5, None if row.sector_rs_20 is None else row.sector_rs_20 > 0)
    points, observed = _add(points, observed, 5, None if row.sector_ret_20 is None else row.sector_ret_20 > 0)
    points, observed = _add(points, observed, 5, row.sector_above_ma)
    points, observed = _add(points, observed, 4, None if row.stock_rs_bench_5 is None else row.stock_rs_bench_5 > 0)
    points, observed = _add(points, observed, 4, None if row.stock_rs_bench_20 is None else row.stock_rs_bench_20 > 0)
    points, observed = _add(points, observed, 3, None if row.stock_rs_sector_5 is None else row.stock_rs_sector_5 > 0)
    points, observed = _add(points, observed, 3, None if row.stock_rs_sector_20 is None else row.stock_rs_sector_20 > 0)
    points, observed = _add(points, observed, 3, row.above_ma25)
    points, observed = _add(points, observed, 3, None if row.vol_change is None else row.vol_change > 0)
    points, observed = _add(points, observed, 5, None if row.bench_ret_20 is None else row.bench_ret_20 > 0)
    # Nikkei (3) and overseas markets (2) are not on this plan.
    points, observed = _add(points, observed, 3, None if row.breadth is None else row.breadth > 0.5)
    points, observed = _add(points, observed, 2, None if row.turnover_ratio is None else row.turnover_ratio > 1.0)
    coverage = observed / 100.0
    if coverage >= 0.75:
        confidence = "高"
    elif coverage >= 0.45:
        confidence = "中"
    else:
        confidence = "低"
    note = "業績持続性20点・日経平均・海外市場は欠測。欠測は0点。"
    return points, confidence, note


def _listing(book: MasterBook, code: str, day: date) -> Listing | None:
    return book.asof(day).get(code)


def build_candidates(events: list[Event], panel: Panel, book: MasterBook) -> tuple[list[Candidate], dict[str, int]]:
    sectors = sector_daily_returns(panel, book)
    market = market_daily(panel, book)
    bench = panel.series.get(panel.benchmark_code)
    counts = {"events": len(events), "not_prime": 0, "no_timing": 0, "no_benchmark": 0}
    if bench is None:
        counts["no_benchmark"] = len(events)
        return [], counts
    clock = panel.clock
    rows: list[Candidate] = []
    for event in events:
        if event.code == BENCHMARK_CODE:
            continue
        listing = _listing(book, event.code, event.disc_date)
        if listing is None or listing.mkt != PRIME_MARKET or listing.prod != COMMON_STOCK:
            counts["not_prime"] += 1
            continue
        timing = entry_timing(clock, event.disc_date, event.disc_time)
        if timing is None:
            counts["no_timing"] += 1
            continue
        series: Series | None = panel.series.get(event.code)
        pre = timing.pre_date
        stock_5 = series.ret_n(pre, 5) if series else None
        stock_20 = series.ret_n(pre, 20) if series else None
        bench_5 = bench.ret_n(pre, 5)
        bench_20 = bench.ret_n(pre, 20)
        sector_map = sectors.get(listing.sector or "不明", {})
        sector_5 = _window_return(sector_map, clock, pre, 5)
        sector_20 = _window_return(sector_map, clock, pre, 20)
        sector_rs_5 = _sub(sector_5, bench_5)
        sector_rs_20 = _sub(sector_20, bench_20)
        stock_rs_b5 = _sub(stock_5, bench_5)
        stock_rs_b20 = _sub(stock_20, bench_20)
        stock_rs_s5 = _sub(stock_5, sector_5)
        stock_rs_s20 = _sub(stock_20, sector_20)
        above = None
        vol = None
        va = 0.0
        if series is not None and series.at(pre) is not None:
            ma = series.ma(pre, 25)
            close = series.adj_c[series.at(pre)]
            above = None if ma is None else close > ma
            vol = series.vol_change(pre, 20)
            va = series.va[series.at(pre)]
        mkt = market.get(pre, {})
        breadth = mkt.get("breadth")
        turnover_ratio = mkt.get("turnover_ratio")
        market_down = None if bench_20 is None else bench_20 <= 0.0
        c1 = event.c0 and _positive(sector_rs_20)
        c2 = event.c0 and _positive(stock_rs_b20) and _positive(stock_rs_s20)
        c3 = c2 and _positive(sector_rs_20)
        row = Candidate(
            event=event,
            name=listing.name,
            sector=listing.sector,
            scale=listing.scale,
            entry_date=timing.entry_date,
            pre_date=pre,
            stock_ret_5=stock_5,
            stock_ret_20=stock_20,
            bench_ret_5=bench_5,
            bench_ret_20=bench_20,
            sector_ret_5=sector_5,
            sector_ret_20=sector_20,
            sector_rs_5=sector_rs_5,
            sector_rs_20=sector_rs_20,
            stock_rs_bench_5=stock_rs_b5,
            stock_rs_bench_20=stock_rs_b20,
            stock_rs_sector_5=stock_rs_s5,
            stock_rs_sector_20=stock_rs_s20,
            above_ma25=above,
            vol_change=vol,
            pre_runup_20=stock_20,
            breadth=breadth if isinstance(breadth, float) else None,
            turnover_ratio=turnover_ratio if isinstance(turnover_ratio, float) else None,
            market_down=market_down,
            sector_above_ma=_above_ma(sector_map, clock, pre, 25),
            c1=c1,
            c2=c2,
            c3=c3,
            score=0.0,
            confidence="低",
            score_note="",
            va=va,
        )
        points, confidence, note = score_candidate(row)
        row.score = points
        row.confidence = confidence
        row.score_note = note
        rows.append(row)
    counts["candidates"] = len(rows)
    counts["c0"] = sum(row.event.c0 for row in rows)
    counts["c1"] = sum(row.c1 for row in rows)
    counts["c2"] = sum(row.c2 for row in rows)
    counts["c3"] = sum(row.c3 for row in rows)
    return rows, counts
