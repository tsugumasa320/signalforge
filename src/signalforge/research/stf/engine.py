"""Daily simulator. Signals use the close. Fills use the next open."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from signalforge.research.stf.rules import DELIST_PENALTY, ELEC_SECTOR, SEMI_CODES, StrategySpec
from signalforge.research.stf.signals import Snap, Target, allocate, rank_candidates


@dataclass
class Lot:
    shares: float
    avg_cost: float
    month_weight: float
    halved: bool
    entry: date


@dataclass
class DailyRow:
    day: date
    equity: float
    cash: float
    gross: float
    n_hold: int
    semi_weight: float
    elec_weight: float
    top_weight: float
    benchmark: float | None
    cum_costs: float = 0.0
    cum_interest: float = 0.0
    cum_trades: int = 0
    cum_notional: float = 0.0


@dataclass
class SimResult:
    spec: StrategySpec
    daily: list[DailyRow]
    trades: int = 0
    traded_notional: float = 0.0
    costs: float = 0.0
    interest: float = 0.0
    pnl_by_code: dict[str, float] = field(default_factory=dict)
    closures: list[tuple[date, date]] = field(default_factory=list)
    open_holding_days: list[int] = field(default_factory=list)
    delist_exits: int = 0
    deferred_days: int = 0
    ruined: bool = False
    exits: dict[str, int] = field(default_factory=dict)
    bench_missing_signals: int = 0


@dataclass
class Panel:
    sessions: list[date]
    snaps: dict[date, dict[str, Snap]]
    universe: dict[date, dict[str, tuple[str, str]]]
    month_ends: set[date]
    benchmark: dict[date, float]
    last_session: dict[str, date]
    last_close: dict[str, float]
    names: dict[str, str] = field(default_factory=dict)
    revisions: dict[date, dict[str, str]] = field(default_factory=dict)


def _num(value: float | None) -> float | None:
    if value is None or value != value:
        return None
    return float(value)


def _session_index(panel: Panel) -> dict[date, int]:
    return {day: i for i, day in enumerate(panel.sessions)}


def _bench_return(panel: Panel, index: dict[date, int], day: date, lookback: int) -> float | None:
    idx = index[day]
    if idx < lookback:
        return None
    prev = panel.benchmark.get(panel.sessions[idx - lookback])
    now = panel.benchmark.get(day)
    if prev is None or now is None or prev <= 0.0:
        return None
    return now / prev - 1.0


def _bench_above_sma(panel: Panel, index: dict[date, int], day: date, window: int) -> bool:
    idx = index[day]
    if idx + 1 < window:
        return False
    values: list[float] = []
    for j in range(idx - window + 1, idx + 1):
        level = panel.benchmark.get(panel.sessions[j])
        if level is None or level <= 0.0:
            return False
        values.append(level)
    last = values[-1]
    return last > (sum(values) / len(values))


def _month_targets(
    panel: Panel,
    index: dict[date, int],
    day: date,
    spec: StrategySpec,
    lots: dict[str, Lot],
) -> dict[str, Target] | None:
    """``None`` when the benchmark is missing and the book must be left unchanged."""
    if _bench_return(panel, index, day, 20) is None or _bench_return(panel, index, day, 60) is None:
        return None
    if spec.regime_sma and not _bench_above_sma(panel, index, day, spec.regime_sma):
        return {code: Target(0.0, 0.0, False) for code in lots}
    snaps = panel.snaps.get(day, {})
    universe = panel.universe.get(day, {})
    sectors = {code: info[1] for code, info in universe.items() if len(info) > 1}
    markets = {code: info[2] for code, info in universe.items() if len(info) > 2}
    rows = [(code, snaps[code]) for code in universe if code in snaps]
    ranked = rank_candidates(
        rows,
        _bench_return(panel, index, day, 20),
        _bench_return(panel, index, day, 60),
        spec,
        sectors=sectors,
        markets=markets,
        revisions=panel.revisions.get(day),
    )
    targets = allocate(ranked, spec)
    if spec.overlay and spec.stop is not None:
        for code in list(targets):
            lot = lots.get(code)
            snap = snaps.get(code)
            if lot is None or snap is None or snap.adj_c is None or lot.avg_cost <= 0.0:
                continue
            if snap.adj_c <= lot.avg_cost * (1.0 + spec.stop):
                del targets[code]
    for code in lots:
        targets.setdefault(code, Target(0.0, 0.0, False))
    return targets


def _overlay_targets(
    panel: Panel,
    day: date,
    spec: StrategySpec,
    lots: dict[str, Lot],
    exits: dict[str, int],
) -> dict[str, Target] | None:
    if not spec.overlay or not lots:
        return None
    snaps = panel.snaps.get(day, {})
    out: dict[str, Target] = {}
    changed = False
    for code, lot in lots.items():
        snap = snaps.get(code)
        close = snap.adj_c if snap is not None else None
        if close is None or lot.month_weight <= 0.0:
            out[code] = Target(lot.month_weight, lot.month_weight, lot.halved)
            continue
        stop_hit = (
            spec.stop is not None and lot.avg_cost > 0.0 and close <= lot.avg_cost * (1.0 + spec.stop)
        )
        below75 = snap is not None and snap.sma75 is not None and close < snap.sma75
        below25 = snap is not None and snap.sma25 is not None and close < snap.sma25
        if stop_hit:
            out[code] = Target(0.0, 0.0, False)
            exits["stop"] = exits.get("stop", 0) + 1
            changed = True
        elif below75:
            out[code] = Target(0.0, 0.0, False)
            exits["sma75"] = exits.get("sma75", 0) + 1
            changed = True
        elif below25 and not lot.halved:
            out[code] = Target(lot.month_weight * 0.5, lot.month_weight, True)
            exits["sma25_half"] = exits.get("sma25_half", 0) + 1
            changed = True
        else:
            weight = lot.month_weight * (0.5 if lot.halved else 1.0)
            out[code] = Target(weight, lot.month_weight, lot.halved)
    if not changed:
        return None
    return out


def _apply_target(
    lots: dict[str, Lot],
    code: str,
    target: Target,
    price: float,
    session: date,
    cash: float,
    equity_basis: float,
    spec: StrategySpec,
    result: SimResult,
) -> float:
    lot = lots.get(code)
    old = 0.0 if lot is None else lot.shares
    new = 0.0 if target.weight <= 1e-12 or price <= 0.0 else target.weight * equity_basis / price
    delta = new - old
    if abs(delta) * price < 1.0 and not (old > 0.0 and new <= 1e-12):
        if lot is not None and new > 0.0:
            lot.month_weight = target.month_weight
            lot.halved = target.halved
        return cash
    if delta < -1e-12:
        notional = (-delta) * price
        cash += notional * (1.0 - spec.one_way)
        result.costs += notional * spec.one_way
        result.traded_notional += abs(notional)
        result.trades += 1
    elif delta > 1e-12:
        notional = delta * price
        cash -= notional * (1.0 + spec.one_way)
        result.costs += notional * spec.one_way
        result.traded_notional += notional
        result.trades += 1
    if new <= 1e-8:
        if lot is not None:
            result.closures.append((lot.entry, session))
            del lots[code]
        return cash
    if lot is None or old <= 1e-8:
        lots[code] = Lot(
            shares=new,
            avg_cost=price,
            month_weight=target.month_weight,
            halved=target.halved,
            entry=session,
        )
        return cash
    if new > old:
        lot.avg_cost = (old * lot.avg_cost + (new - old) * price) / new
    lot.shares = new
    lot.month_weight = target.month_weight
    lot.halved = target.halved
    return cash


def _price_pnl(old: float, new: float, prev: float | None, open_px: float | None, close: float | None, traded: bool) -> float:
    if prev is None or close is None:
        return 0.0
    if not traded:
        return old * (close - prev)
    px = open_px if open_px is not None else close
    return old * (px - prev) + new * (close - px)


def simulate(panel: Panel, spec: StrategySpec, capital: float) -> SimResult:
    result = SimResult(spec=spec, daily=[])
    lots: dict[str, Lot] = {}
    cash = float(capital)
    pending: dict[str, Target] | None = None
    equity_basis = float(capital)
    prev_close: dict[str, float] = {}
    sector_of: dict[str, str] = {}
    pending_waits: dict[str, int] = {}
    index = _session_index(panel)

    for i, session in enumerate(panel.sessions):
        if result.ruined:
            prev = result.daily[-1]
            result.daily.append(
                DailyRow(
                    session,
                    prev.equity,
                    prev.cash,
                    0.0,
                    0,
                    0.0,
                    0.0,
                    0.0,
                    panel.benchmark.get(session),
                    prev.cum_costs,
                    prev.cum_interest,
                    prev.cum_trades,
                    prev.cum_notional,
                )
            )
            continue

        start_shares = {code: lot.shares for code, lot in lots.items()}
        traded_at: dict[str, float] = {}

        if i > 0:
            span = (session - panel.sessions[i - 1]).days
            interest = max(0.0, -cash) * spec.finance * span / 365.0
            cash -= interest
            result.interest += interest

        for code in list(lots):
            last = panel.last_session.get(code)
            if last is None or session <= last:
                continue
            lot = lots.pop(code)
            px = panel.last_close.get(code, lot.avg_cost)
            notional = lot.shares * px
            haircut = spec.one_way + DELIST_PENALTY
            cash += notional * (1.0 - haircut)
            result.costs += notional * haircut
            result.traded_notional += notional
            result.trades += 1
            result.delist_exits += 1
            result.exits["delist"] = result.exits.get("delist", 0) + 1
            result.closures.append((lot.entry, session))
            traded_at[code] = px
            prev = prev_close.get(code, px)
            result.pnl_by_code[code] = result.pnl_by_code.get(code, 0.0) + lot.shares * (px - prev)

        if pending is not None:
            # One halted name does not block the rest of the basket.
            # Sells (weight 0) go first. A name with no open is retried for 5 sessions.
            still: dict[str, Target] = {}
            for code, target in sorted(pending.items(), key=lambda item: item[1].weight):
                if target.weight <= 0.0 and code not in lots:
                    continue
                snap = panel.snaps.get(session, {}).get(code)
                px = _num(snap.adj_o) if snap is not None else None
                if px is None or px <= 0.0:
                    last = panel.last_session.get(code)
                    if last is not None and session > last:
                        continue
                    pending_waits[code] = pending_waits.get(code, 0) + 1
                    if pending_waits[code] <= 5:
                        still[code] = target
                        result.deferred_days += 1
                    continue
                pending_waits.pop(code, None)
                cash = _apply_target(
                    lots, code, target, px, session, cash, equity_basis, spec, result
                )
                traded_at[code] = px
            pending = still or None

        snaps = panel.snaps.get(session, {})
        gross = 0.0
        for code, lot in lots.items():
            snap = snaps.get(code)
            close = _num(snap.adj_c) if snap is not None else None
            if close is None or close <= 0.0:
                close = prev_close.get(code)
            if close is None:
                continue
            gross += lot.shares * close
            old = start_shares.get(code, 0.0)
            prev = prev_close.get(code, close)
            traded = code in traded_at and panel.last_session.get(code, session) >= session
            # Delist path already booked pnl and removed the lot.
            result.pnl_by_code[code] = result.pnl_by_code.get(code, 0.0) + _price_pnl(
                old, lot.shares, prev, traded_at.get(code), close, traded
            )
            prev_close[code] = close

        for code, old in start_shares.items():
            if code in lots or code not in traded_at:
                continue
            if panel.last_session.get(code, session) < session:
                continue  # delist pnl already booked
            prev = prev_close.get(code)
            snap = snaps.get(code)
            close = _num(snap.adj_c) if snap is not None else None
            if close is None:
                close = traded_at[code]
            result.pnl_by_code[code] = result.pnl_by_code.get(code, 0.0) + _price_pnl(
                old, 0.0, prev, traded_at[code], close, True
            )

        equity = cash + gross
        if i > 0 and equity <= 0.0:
            result.ruined = True
            equity = 0.0
            cash = 0.0
            gross = 0.0
            lots.clear()

        if session in panel.universe:
            for code, info in panel.universe[session].items():
                sector_of[code] = info[1] if len(info) > 1 else ""
                panel.names[code] = info[0]

        semi = 0.0
        elec = 0.0
        top = 0.0
        if equity > 0.0:
            for code, lot in lots.items():
                weight = lot.shares * prev_close.get(code, 0.0) / equity
                top = max(top, weight)
                if code in SEMI_CODES:
                    semi += weight
                if sector_of.get(code) == ELEC_SECTOR:
                    elec += weight

        result.daily.append(
            DailyRow(
                day=session,
                equity=equity,
                cash=cash,
                gross=gross,
                n_hold=len(lots),
                semi_weight=semi,
                elec_weight=elec,
                top_weight=top,
                benchmark=panel.benchmark.get(session),
                cum_costs=result.costs,
                cum_interest=result.interest,
                cum_trades=result.trades,
                cum_notional=result.traded_notional,
            )
        )
        if result.ruined:
            continue

        for code in list(prev_close):
            if code not in lots:
                prev_close.pop(code, None)

        if pending is not None:
            continue  # still waiting for a fill; do not stack a new order
        if session in panel.month_ends:
            targets = _month_targets(panel, index, session, spec, lots)
            if targets is None:
                result.bench_missing_signals += 1
            else:
                pending = targets
                equity_basis = equity
        elif spec.overlay:
            over = _overlay_targets(panel, session, spec, lots, result.exits)
            if over is not None:
                pending = over
                equity_basis = equity

    if panel.sessions:
        end = panel.sessions[-1]
        for lot in lots.values():
            result.open_holding_days.append((end - lot.entry).days)
    return result
