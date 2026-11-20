"""Trade statistics. Thresholds are not chosen here."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from signalforge.research.earnings_surprise.config import HEADLINE_HOLD, HEADLINE_STOP, RUNUP_CUT
from signalforge.research.earnings_surprise.simulate import Book, Trade


def is_headline(trade: Trade) -> bool:
    return trade.method == "A" and trade.hold == HEADLINE_HOLD and math.isclose(trade.stop, HEADLINE_STOP)


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def max_drawdown(equity: list[float]) -> float | None:
    if not equity:
        return None
    peak = equity[0]
    worst = 0.0
    for value in equity:
        if value > peak:
            peak = value
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def stats(trades: list[Trade]) -> dict[str, float | int | None]:
    if not trades:
        return {
            "n": 0,
            "win_rate": None,
            "avg_win": None,
            "avg_loss": None,
            "avg_ret": None,
            "pf": None,
            "avg_excess": None,
            "stops": 0,
            "gaps": 0,
        }
    rets = [trade.ret for trade in trades]
    wins = [value for value in rets if value > 0]
    losses = [value for value in rets if value <= 0]
    pnl = [trade.notional * trade.ret for trade in trades]
    gain = sum(value for value in pnl if value > 0)
    loss = -sum(value for value in pnl if value <= 0)
    excess = [trade.excess for trade in trades if trade.excess is not None]
    return {
        "n": len(trades),
        "win_rate": len(wins) / len(trades),
        "avg_win": mean(wins),
        "avg_loss": mean(losses),
        "avg_ret": mean(rets),
        "pf": None if loss == 0 else gain / loss,
        "avg_excess": mean(excess),
        "stops": sum(trade.stopped for trade in trades),
        "gaps": sum(trade.gap_loss for trade in trades),
    }


def capital_stats(book: Book | None) -> dict[str, float | int | None]:
    if book is None or not book.equity:
        return {
            "max_hold": 0,
            "avg_tied": 0.0,
            "max_tied": 0.0,
            "max_dd": None,
            "funded": 0,
            "rejected": 0,
        }
    return {
        "max_hold": max(book.n_hold) if book.n_hold else 0,
        "avg_tied": sum(book.tied) / len(book.tied),
        "max_tied": max(book.tied) if book.tied else 0.0,
        "max_dd": max_drawdown(book.equity),
        "funded": len(book.funded_ids),
        "rejected": len(book.rejected_ids),
    }


def find_book(books: list[Book], strategy: str, method: str = "A", hold: int = HEADLINE_HOLD, stop: float = HEADLINE_STOP) -> Book | None:
    for book in books:
        if book.strategy == strategy and book.method == method and book.hold == hold and math.isclose(book.stop, stop):
            return book
    return None


def grouped(trades: list[Trade], key) -> list[dict]:
    buckets: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        buckets[str(key(trade))].append(trade)
    rows = []
    for name in sorted(buckets):
        row = stats(buckets[name])
        row["bucket"] = name
        rows.append(row)
    return rows


def liquidity_bucket(trade: Trade) -> str:
    if trade.va < 1_000_000_000:
        return "5億–10億"
    if trade.va < 5_000_000_000:
        return "10億–50億"
    return "50億以上"


def runup_bucket(trade: Trade) -> str:
    if trade.pre_runup_20 is None:
        return "不明"
    if trade.pre_runup_20 > RUNUP_CUT:
        return "発表前20日が10%超"
    return "発表前20日が10%以下"


def regime_bucket(trade: Trade) -> str:
    if trade.market_down is True:
        return "下落"
    if trade.market_down is False:
        return "上昇"
    return "不明"


def month_key(trade: Trade) -> str:
    day: date = trade.entry_date
    return f"{day.year:04d}-{day.month:02d}"
