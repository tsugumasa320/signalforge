"""Company-forecast surprises from J-Quants /fins/summary.

Sell-side consensus is not in this feed. An upward revision of the company's
own full-year forecast is stored separately and is never labelled as a
consensus beat. Missing prior forecasts stay missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from signalforge.research.earnings_surprise.config import UNIT_BREAK
from signalforge.research.earnings_surprise.panel import as_date, as_float


def is_nonconsolidated(doc_type: str) -> bool:
    text = doc_type or ""
    return "NonConsolidated" in text or "NonCons" in text


def is_statement(doc_type: str, period: str) -> bool:
    if period in {"1Q", "2Q", "3Q", "FY"}:
        return True
    text = doc_type or ""
    return "Financial" in text or "Forecast" in text or "Revision" in text


def compare_forecast(previous: float | None, current: float | None) -> tuple[bool | None, bool]:
    """Return (revised_up, keep_current_as_baseline).

    ``None`` means the pair cannot be called a revision. A 1000x jump resets
    the baseline and is not an upward revision.
    """
    if current is None:
        return None, False
    if previous is None:
        return None, True
    if previous == 0.0:
        return current > 0.0, True
    ratio = abs(current / previous)
    if ratio >= UNIT_BREAK or ratio <= 1.0 / UNIT_BREAK:
        return None, True
    return current > previous, True


@dataclass
class Event:
    code: str
    disc_date: date
    disc_time: str
    doc_type: str
    period: str
    period_end: str
    fiscal_end: str
    sales: float | None
    op: float | None
    np: float | None
    eps: float | None
    rev_sales: bool | None
    rev_op: bool | None
    rev_np: bool | None
    rev_eps: bool | None
    op_yoy: float | None
    opm_delta: float | None
    c0: bool
    basis: str = "company_forecast_or_yoy"
    consensus_op: float | None = None


def _margin(op: float | None, sales: float | None) -> float | None:
    if op is None or sales is None or sales <= 0:
        return None
    return op / sales


def _period_key(period: str, period_end: date | None) -> tuple[str, int, int] | None:
    if period_end is None or not period:
        return None
    return period, period_end.year, period_end.month


def passes_c0(rev_op: bool | None, op_yoy: float | None, opm_delta: float | None) -> bool:
    if rev_op is True:
        return True
    return (
        op_yoy is not None
        and op_yoy > 0.0
        and opm_delta is not None
        and opm_delta > 0.0
    )


def _prefer_consolidated(events: list[Event]) -> list[Event]:
    consolidated = {event.code for event in events if not is_nonconsolidated(event.doc_type)}
    return [
        event
        for event in events
        if not (is_nonconsolidated(event.doc_type) and event.code in consolidated)
    ]


def _dedup(events: list[Event]) -> list[Event]:
    chosen: dict[tuple, Event] = {}
    for event in events:
        key = (event.code, event.disc_date, event.disc_time, event.fiscal_end, event.period)
        current = chosen.get(key)
        if current is None or (current.op is None and event.op is not None):
            chosen[key] = event
    return list(chosen.values())


def build_events(rows: list[dict]) -> list[Event]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        code = str(row.get("Code") or "").strip()
        disc = as_date(row.get("DiscDate"))
        if not code or disc is None:
            continue
        doc_type = str(row.get("DocType") or "")
        period = str(row.get("CurPerType") or "")
        if not is_statement(doc_type, period):
            continue
        consol = "noncons" if is_nonconsolidated(doc_type) else "cons"
        grouped.setdefault((code, consol), []).append(row)

    events: list[Event] = []
    for (code, _), group in grouped.items():
        group.sort(key=lambda row: (str(row.get("DiscDate")), str(row.get("DiscTime") or ""), str(row.get("DiscNo") or "")))
        last_forecast: dict[str, dict[str, float | None]] = {}
        actuals: dict[tuple[str, int, int], tuple[float | None, float | None]] = {}
        for row in group:
            fiscal_end = str(row.get("CurFYEn") or "")
            forecasts = {
                "sales": as_float(row.get("FSales")),
                "op": as_float(row.get("FOP")),
                "np": as_float(row.get("FNP")),
                "eps": as_float(row.get("FEPS")),
            }
            flags: dict[str, bool | None] = {}
            baseline = last_forecast.get(fiscal_end, {})
            updated = dict(baseline)
            for name, value in forecasts.items():
                flag, keep = compare_forecast(baseline.get(name), value)
                flags[name] = flag
                if keep:
                    updated[name] = value
            if fiscal_end:
                last_forecast[fiscal_end] = updated

            period = str(row.get("CurPerType") or "")
            period_end = as_date(row.get("CurPerEn"))
            sales = as_float(row.get("Sales"))
            op = as_float(row.get("OP"))
            op_yoy: float | None = None
            opm_delta: float | None = None
            key = _period_key(period, period_end)
            if key is not None:
                year_ago = (key[0], key[1] - 1, key[2])
                prior = actuals.get(year_ago)
                if prior is not None and op is not None and prior[1] not in (None, 0.0):
                    op_yoy = (op - prior[1]) / abs(prior[1])
                    margin = _margin(op, sales)
                    prior_margin = _margin(prior[1], prior[0])
                    if margin is not None and prior_margin is not None:
                        opm_delta = margin - prior_margin
                if op is not None or sales is not None:
                    actuals[key] = (sales, op)

            events.append(
                Event(
                    code=code,
                    disc_date=as_date(row.get("DiscDate")),
                    disc_time=str(row.get("DiscTime") or ""),
                    doc_type=str(row.get("DocType") or ""),
                    period=period,
                    period_end="" if period_end is None else period_end.isoformat(),
                    fiscal_end=fiscal_end,
                    sales=sales,
                    op=op,
                    np=as_float(row.get("NP")),
                    eps=as_float(row.get("EPS")),
                    rev_sales=flags["sales"],
                    rev_op=flags["op"],
                    rev_np=flags["np"],
                    rev_eps=flags["eps"],
                    op_yoy=op_yoy,
                    opm_delta=opm_delta,
                    c0=passes_c0(flags["op"], op_yoy, opm_delta),
                )
            )
    return _dedup(_prefer_consolidated(events))
