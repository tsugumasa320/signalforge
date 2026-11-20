"""Performance statistics. Risk-free rate is zero, as frozen before the run."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from signalforge.research.stf.engine import DailyRow, SimResult


@dataclass
class WindowStats:
    start: date
    end: date
    start_equity: float
    end_equity: float
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    mdd_peak: date | None
    mdd_trough: date | None
    mdd_recovered: date | None
    max_underwater_days: int
    max_down_streak: int
    trades: int
    trades_per_year: float
    avg_holdings: float
    avg_holding_days: float | None
    traded_notional: float
    costs: float
    interest: float
    avg_leverage: float
    max_leverage: float
    max_gross: float
    avg_cash_ratio: float
    min_cash_ratio: float
    avg_semi_weight: float
    avg_elec_weight: float
    avg_top_weight: float
    ruined: bool
    yearly: list[tuple[int, float]]
    monthly: list[tuple[str, float]]
    bench_total_return: float | None
    bench_cagr: float | None
    excess_cagr: float | None


def _slice(rows: list[DailyRow], start: date, end: date) -> list[DailyRow]:
    return [row for row in rows if start <= row.day <= end]


def _cagr(start_equity: float, end_equity: float, start: date, end: date) -> float:
    years = max((end - start).days, 1) / 365.25
    if start_equity <= 0.0 or end_equity <= 0.0:
        return -1.0
    return (end_equity / start_equity) ** (1.0 / years) - 1.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _max_drawdown(rows: list[DailyRow]) -> tuple[float, date | None, date | None, date | None, int]:
    peak = rows[0].equity
    peak_day = rows[0].day
    trough_day = rows[0].day
    max_dd = 0.0
    mdd_peak: date | None = None
    mdd_trough: date | None = None
    underwater_since: date | None = None
    max_under = 0
    recovered: date | None = None
    pending_recovery = False
    for row in rows:
        if row.equity >= peak:
            if underwater_since is not None:
                max_under = max(max_under, (row.day - underwater_since).days)
                if pending_recovery and mdd_peak == underwater_since:
                    recovered = row.day
            peak = row.equity
            peak_day = row.day
            underwater_since = None
            pending_recovery = False
            continue
        dd = row.equity / peak - 1.0 if peak > 0.0 else -1.0
        if underwater_since is None:
            underwater_since = peak_day
        if dd < max_dd:
            max_dd = dd
            mdd_peak = peak_day
            mdd_trough = row.day
            recovered = None
            pending_recovery = True
    if underwater_since is not None:
        max_under = max(max_under, (rows[-1].day - underwater_since).days)
    return max_dd, mdd_peak, mdd_trough, recovered, max_under


def _period_returns(rows: list[DailyRow], kind: str) -> list[tuple[str, float]]:
    buckets: dict[str, DailyRow] = {}
    for row in rows:
        key = f"{row.day.year:04d}-{row.day.month:02d}" if kind == "month" else f"{row.day.year:04d}"
        buckets[key] = row
    keys = sorted(buckets)
    out: list[tuple[str, float]] = []
    prev_equity = rows[0].equity
    # First bucket is measured from the window start, not from a full prior period.
    first = True
    prev_key_equity = prev_equity
    last_seen = None
    for key in keys:
        end_equity = buckets[key].equity
        if first:
            base = rows[0].equity
            first = False
        else:
            base = prev_key_equity
        if base > 0.0:
            out.append((key, end_equity / base - 1.0))
        prev_key_equity = end_equity
        last_seen = key
    _ = last_seen
    return out


def summarize(result: SimResult, start: date, end: date, capital: float) -> WindowStats:
    rows = _slice(result.daily, start, end)
    if len(rows) < 2:
        raise ValueError(f"not enough sessions in {start} .. {end}")
    rets: list[float] = []
    for prev, row in zip(rows, rows[1:]):
        if prev.equity > 0.0:
            rets.append(row.equity / prev.equity - 1.0)
    mean = sum(rets) / len(rets) if rets else 0.0
    vol_d = _std(rets)
    vol = vol_d * math.sqrt(252.0)
    sharpe = (mean / vol_d * math.sqrt(252.0)) if vol_d > 0.0 else 0.0
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in rets) / len(rets)) if rets else 0.0
    sortino = (mean / downside * math.sqrt(252.0)) if downside > 0.0 else 0.0
    mdd, peak, trough, recovered, under = _max_drawdown(rows)
    streak = 0
    max_streak = 0
    for value in rets:
        if value < 0.0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    years = max((rows[-1].day - rows[0].day).days, 1) / 365.25
    leverages = [row.gross / row.equity for row in rows if row.equity > 0.0]
    cash_ratios = [row.cash / row.equity for row in rows if row.equity > 0.0]
    bench_start = next((row.benchmark for row in rows if row.benchmark), None)
    bench_end = next((row.benchmark for row in reversed(rows) if row.benchmark), None)
    bench_total = None
    bench_cagr = None
    if bench_start and bench_end and bench_start > 0.0:
        bench_total = bench_end / bench_start - 1.0
        bench_cagr = _cagr(bench_start, bench_end, rows[0].day, rows[-1].day)
    total = rows[-1].equity / rows[0].equity - 1.0 if rows[0].equity > 0.0 else -1.0
    cagr = _cagr(rows[0].equity, rows[-1].equity, rows[0].day, rows[-1].day)
    _ = capital
    closed = [
        (exit_day - entry).days
        for entry, exit_day in result.closures
        if rows[0].day <= exit_day <= rows[-1].day
    ]
    trades = rows[-1].cum_trades - rows[0].cum_trades
    return WindowStats(
        start=rows[0].day,
        end=rows[-1].day,
        start_equity=rows[0].equity,
        end_equity=rows[-1].equity,
        total_return=total,
        cagr=cagr,
        volatility=vol,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=mdd,
        mdd_peak=peak,
        mdd_trough=trough,
        mdd_recovered=recovered,
        max_underwater_days=under,
        max_down_streak=max_streak,
        trades=trades,
        trades_per_year=trades / years,
        avg_holdings=sum(row.n_hold for row in rows) / len(rows),
        avg_holding_days=(sum(closed) / len(closed)) if closed else None,
        traded_notional=rows[-1].cum_notional - rows[0].cum_notional,
        costs=rows[-1].cum_costs - rows[0].cum_costs,
        interest=rows[-1].cum_interest - rows[0].cum_interest,
        avg_leverage=sum(leverages) / len(leverages) if leverages else 0.0,
        max_leverage=max(leverages) if leverages else 0.0,
        max_gross=max(row.gross for row in rows),
        avg_cash_ratio=sum(cash_ratios) / len(cash_ratios) if cash_ratios else 0.0,
        min_cash_ratio=min(cash_ratios) if cash_ratios else 0.0,
        avg_semi_weight=sum(row.semi_weight for row in rows) / len(rows),
        avg_elec_weight=sum(row.elec_weight for row in rows) / len(rows),
        avg_top_weight=sum(row.top_weight for row in rows) / len(rows),
        ruined=result.ruined,
        yearly=[(int(key), value) for key, value in _period_returns(rows, "year")],
        monthly=_period_returns(rows, "month"),
        bench_total_return=bench_total,
        bench_cagr=bench_cagr,
        excess_cagr=(cagr - bench_cagr) if bench_cagr is not None else None,
    )
