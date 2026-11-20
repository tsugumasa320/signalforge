"""Daily-bar entries, stops, and a fixed yen account.

Method B (next-session VWAP) is not simulated: this API plan has no minute bars.
Same-day stop and time-exit collisions take the stop. A gap through the stop
fills at the open, not at the stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from signalforge.research.earnings_surprise.config import (
    ACCOUNT_JPY,
    COMMISSION,
    ENTRY_METHODS,
    HEADLINE_HOLD,
    HEADLINE_STOP,
    HOLDS,
    LOT,
    MIN_TURNOVER_JPY,
    PER_NAME_JPY,
    SLIPPAGE,
    STOPS,
)
from signalforge.research.earnings_surprise.features import Candidate
from signalforge.research.earnings_surprise.panel import Panel, Series, split_label

COST_IN = 1.0 + COMMISSION + SLIPPAGE
COST_OUT = 1.0 - COMMISSION - SLIPPAGE


def _gates(row: Candidate) -> list[str]:
    names: list[str] = []
    if row.event.c0:
        names.append("C0")
    if row.c1:
        names.append("C1")
    if row.c2:
        names.append("C2")
    if row.c3:
        names.append("C3")
    return names


@dataclass
class Trade:
    id: str
    strategy: str
    method: str
    hold: int
    stop: float
    code: str
    name: str
    sector: str
    scale: str
    disc_date: date
    disc_time: str
    entry_date: date
    entry_px: float
    exit_date: date
    exit_px: float
    exit_reason: str
    shares: int
    notional: float
    deploy: float
    proceeds: float
    ret: float
    bench_ret: float | None
    excess: float | None
    stopped: bool
    gap_loss: bool
    score: float
    confidence: str
    pre_runup_20: float | None
    market_down: bool | None
    va: float
    split: str
    entry_adj: float
    exit_adj: float


@dataclass
class Exclusion:
    code: str
    name: str
    disc_date: date
    strategy: str
    method: str
    hold: int
    stop: float
    reason: str


@dataclass
class Book:
    strategy: str
    method: str
    hold: int
    stop: float
    funded_ids: set[str] = field(default_factory=set)
    rejected_ids: set[str] = field(default_factory=set)
    days: list[date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    tied: list[float] = field(default_factory=list)
    n_hold: list[int] = field(default_factory=list)


def _bench_return(panel: Panel, entry: date, exit: date, at_open: bool) -> float | None:
    bench = panel.bench()
    i0 = bench.at(entry)
    i1 = bench.at(exit)
    if i0 is None or i1 is None:
        return None
    start = bench.adj_o[i0]
    end = bench.adj_o[i1] if at_open else bench.adj_c[i1]
    if start <= 0 or end <= 0:
        return None
    return end / start - 1.0


def _walk(
    series: Series,
    clock: list[date],
    entry_index: int,
    hold: int,
    adj_fill: float,
    stop: float,
    method: str,
) -> tuple[date, float, str, bool, bool] | str:
    stop_px = adj_fill * (1.0 + stop)
    last_index = entry_index + hold - 1
    if last_index >= len(clock):
        return "期間不足"
    last_close: float | None = None
    last_day: date | None = None
    bought_above_open = method == "C"
    for pos in range(entry_index, last_index + 1):
        day = clock[pos]
        bar = series.at(day)
        if bar is None or series.bad(bar):
            continue
        opened = series.adj_o[bar]
        low = series.adj_l[bar]
        closed = series.adj_c[bar]
        last_close = closed
        last_day = day
        if pos == entry_index and bought_above_open and opened < adj_fill and low <= stop_px:
            return day, stop_px, "損切り", True, False
        if opened <= stop_px and not (pos == entry_index and method == "A"):
            return day, opened, "損切り", True, True
        if low <= stop_px:
            return day, stop_px, "損切り", True, False
        if pos == last_index:
            return day, closed, "期間満了", False, False
    if last_close is None or last_day is None:
        return "売買停止"
    return last_day, last_close, "途中データ欠落", False, False


def _try_fill(
    row: Candidate,
    series: Series,
    method: str,
) -> tuple[float, float, int] | str:
    entry_i = series.at(row.entry_date)
    pre_i = series.at(row.pre_date)
    if entry_i is None:
        return "売買停止"
    if pre_i is None:
        return "履歴不足"
    if series.bad(entry_i) or series.bad(pre_i):
        return "価格異常"
    if series.va[pre_i] < MIN_TURNOVER_JPY:
        return "流動性不足"
    raw_o = series.raw_o[entry_i]
    adj_o = series.adj_o[entry_i]
    if method == "A":
        adj_fill = adj_o
        raw_fill = raw_o
    else:
        trigger = series.adj_h[pre_i]
        if series.adj_h[entry_i] <= trigger:
            return "高値未更新"
        adj_fill = adj_o if adj_o >= trigger else trigger
        raw_fill = adj_fill * (raw_o / adj_o)
    shares = int(PER_NAME_JPY // raw_fill // LOT) * LOT
    if shares < LOT:
        return "単元未満"
    return adj_fill, raw_fill, shares


def simulate(rows: list[Candidate], panel: Panel) -> tuple[list[Trade], list[Exclusion]]:
    trades: list[Trade] = []
    excluded: list[Exclusion] = []
    clock = panel.clock
    index = {day: pos for pos, day in enumerate(clock)}
    max_hold = max(HOLDS)
    for row in rows:
        strategies = _gates(row)
        if not strategies:
            continue
        series = panel.series.get(row.event.code)
        entry_index = index.get(row.entry_date)
        if series is None or entry_index is None:
            for strategy in strategies:
                excluded.append(
                    Exclusion(row.event.code, row.name, row.event.disc_date, strategy, "A", HEADLINE_HOLD, STOPS[1], "売買停止")
                )
            continue
        if entry_index + max_hold - 1 >= len(clock):
            for strategy in strategies:
                for method in ENTRY_METHODS:
                    excluded.append(
                        Exclusion(row.event.code, row.name, row.event.disc_date, strategy, method, max_hold, HEADLINE_STOP, "期間不足")
                    )
            continue
        for method in ENTRY_METHODS:
            filled = _try_fill(row, series, method)
            if isinstance(filled, str):
                for strategy in strategies:
                    excluded.append(
                        Exclusion(row.event.code, row.name, row.event.disc_date, strategy, method, HEADLINE_HOLD, HEADLINE_STOP, filled)
                    )
                continue
            adj_fill, raw_fill, shares = filled
            notional = shares * raw_fill
            for strategy in strategies:
                for hold in HOLDS:
                    for stop in STOPS:
                        walked = _walk(series, clock, entry_index, hold, adj_fill, stop, method)
                        if isinstance(walked, str):
                            excluded.append(
                                Exclusion(row.event.code, row.name, row.event.disc_date, strategy, method, hold, stop, walked)
                            )
                            continue
                        exit_date, exit_adj, reason, stopped, gap = walked
                        deploy = notional * COST_IN
                        proceeds = notional * (exit_adj / adj_fill) * COST_OUT
                        ret = proceeds / deploy - 1.0
                        at_open = gap
                        bench = _bench_return(panel, row.entry_date, exit_date, at_open)
                        excess = None if bench is None else ret - bench
                        trade_id = f"{row.event.code}|{row.event.disc_date.isoformat()}|{strategy}|{method}|{hold}|{stop}"
                        trades.append(
                            Trade(
                                id=trade_id,
                                strategy=strategy,
                                method=method,
                                hold=hold,
                                stop=stop,
                                code=row.event.code,
                                name=row.name,
                                sector=row.sector,
                                scale=row.scale,
                                disc_date=row.event.disc_date,
                                disc_time=row.event.disc_time,
                                entry_date=row.entry_date,
                                entry_px=raw_fill,
                                exit_date=exit_date,
                                exit_px=raw_fill * (exit_adj / adj_fill),
                                exit_reason=reason,
                                shares=shares,
                                notional=notional,
                                deploy=deploy,
                                proceeds=proceeds,
                                ret=ret,
                                bench_ret=bench,
                                excess=excess,
                                stopped=stopped,
                                gap_loss=gap,
                                score=row.score,
                                confidence=row.confidence,
                                pre_runup_20=row.pre_runup_20,
                                market_down=row.market_down,
                                va=row.va,
                                split=split_label(clock, row.entry_date),
                                entry_adj=adj_fill,
                                exit_adj=exit_adj,
                            )
                        )
    return trades, excluded


def build_books(trades: list[Trade], panel: Panel, account: float = ACCOUNT_JPY) -> list[Book]:
    grouped: dict[tuple[str, str, int, float], list[Trade]] = {}
    for trade in trades:
        grouped.setdefault((trade.strategy, trade.method, trade.hold, trade.stop), []).append(trade)
    books: list[Book] = []
    for key in sorted(grouped):
        books.append(_one_book(key, grouped[key], panel, account))
    return books


def _one_book(key: tuple[str, str, int, float], trades: list[Trade], panel: Panel, account: float) -> Book:
    strategy, method, hold, stop = key
    by_entry: dict[date, list[Trade]] = {}
    for trade in trades:
        by_entry.setdefault(trade.entry_date, []).append(trade)
    for day, items in by_entry.items():
        items.sort(key=lambda trade: (-trade.score, trade.code))
    book = Book(strategy, method, hold, stop)
    if not trades:
        return book
    active: list[Trade] = []
    cash = account
    start = min(trade.entry_date for trade in trades)
    end = max(trade.exit_date for trade in trades)
    for day in panel.clock:
        if day < start or day > end:
            continue
        still: list[Trade] = []
        for trade in active:
            if trade.exit_date <= day:
                cash += trade.proceeds
            else:
                still.append(trade)
        active = still
        for trade in by_entry.get(day, []):
            if cash >= trade.deploy:
                cash -= trade.deploy
                book.funded_ids.add(trade.id)
                if trade.exit_date <= day:
                    cash += trade.proceeds
                else:
                    active.append(trade)
            else:
                book.rejected_ids.add(trade.id)
        marked = 0.0
        tied = 0.0
        for trade in active:
            price = panel.series[trade.code].close_asof(day)
            if price is None:
                price = trade.entry_adj
            marked += trade.notional * (price / trade.entry_adj) * COST_OUT
            tied += trade.deploy
        book.days.append(day)
        book.equity.append(cash + marked)
        book.tied.append(tied)
        book.n_hold.append(len(active))
    return book
