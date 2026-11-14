"""通期実績を、決算期末から90日後以降だけ使えるとみなす。"""

from __future__ import annotations

from datetime import date, timedelta

from signalforge.research.trend_screen.fundamentals import AnnualPoint

REPORT_LAG_DAYS = 90


def available_annuals(annuals: list[AnnualPoint], as_of: date) -> list[AnnualPoint]:
    ordered = sorted(annuals, key=lambda row: row.fiscal_end)
    usable: list[AnnualPoint] = []
    for row in ordered:
        try:
            end = date.fromisoformat(row.fiscal_end[:10])
        except ValueError:
            continue
        if end + timedelta(days=REPORT_LAG_DAYS) <= as_of:
            usable.append(row)
    return usable


def growth_ok(annuals: list[AnnualPoint], as_of: date) -> bool | None:
    """売上・営業利益・EPSが直近3期で連続増加なら True。足りなければ None。"""
    usable = available_annuals(annuals, as_of)
    if len(usable) < 3:
        return None
    last3 = usable[-3:]
    for field in ("sales", "operating_income", "eps"):
        values = [getattr(row, field) for row in last3]
        if any(value is None for value in values):
            return None
        if not (values[0] < values[1] < values[2]):  # type: ignore[operator]
            return False
    return True
