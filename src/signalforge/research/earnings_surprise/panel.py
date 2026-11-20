"""Price panel, listing snapshots, and announcement timing.

Relative-strength windows end on the last close before the announcement is
public. The entry is the next open we can actually trade with daily bars.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, datetime


def as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number:
            return None
        return number
    text = str(value).strip()
    if not text or text in {"-", "None", "null"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number:
        return None
    return number


@dataclass(frozen=True)
class Timing:
    entry_date: date
    pre_date: date


def entry_timing(clock: list[date], disc_date: date, disc_time: str) -> Timing | None:
    """Map an announcement to the pre-news close and the first tradable open.

    Daily bars have no post-announcement print. A release at or after 09:00
    therefore waits for the next session's open. A release before 09:00 can
    use that session's open. Missing times are treated as after the close.
    """
    if not clock:
        return None
    clock_time = disc_time or "99:99:99"
    if clock_time < "09:00:00":
        entry_pos = bisect.bisect_left(clock, disc_date)
        pre_pos = entry_pos - 1
    elif clock_time < "15:00:00":
        entry_pos = bisect.bisect_right(clock, disc_date)
        pre_pos = bisect.bisect_left(clock, disc_date) - 1
    else:
        pre_pos = bisect.bisect_right(clock, disc_date) - 1
        entry_pos = pre_pos + 1
    if pre_pos < 0 or entry_pos >= len(clock):
        return None
    return Timing(clock[entry_pos], clock[pre_pos])


def split_label(clock: list[date], day: date, design: float = 0.60, validate: float = 0.80) -> str:
    pos = bisect.bisect_left(clock, day)
    if pos >= len(clock) or clock[pos] != day:
        pos = max(0, min(pos, len(clock) - 1))
    n = len(clock)
    if pos < int(n * design):
        return "設計"
    if pos < int(n * validate):
        return "検証"
    return "検証外"


@dataclass
class Series:
    code: str
    dates: list[date]
    raw_o: list[float]
    raw_h: list[float]
    raw_l: list[float]
    raw_c: list[float]
    adj_o: list[float]
    adj_h: list[float]
    adj_l: list[float]
    adj_c: list[float]
    va: list[float]
    vo: list[float]
    loc: dict[date, int]

    @classmethod
    def from_rows(cls, code: str, rows: list[dict]) -> Series:
        cleaned: dict[date, dict] = {}
        for row in rows:
            day = as_date(row.get("Date") or row.get("date"))
            if day is None:
                continue
            raw_o = as_float(row.get("O"))
            raw_h = as_float(row.get("H"))
            raw_l = as_float(row.get("L"))
            raw_c = as_float(row.get("C"))
            adj_o = as_float(row.get("AdjO")) or raw_o
            adj_h = as_float(row.get("AdjH")) or raw_h
            adj_l = as_float(row.get("AdjL")) or raw_l
            adj_c = as_float(row.get("AdjC")) or raw_c
            if None in (raw_o, raw_h, raw_l, raw_c, adj_o, adj_h, adj_l, adj_c):
                continue
            cleaned[day] = {
                "raw_o": raw_o,
                "raw_h": raw_h,
                "raw_l": raw_l,
                "raw_c": raw_c,
                "adj_o": adj_o,
                "adj_h": adj_h,
                "adj_l": adj_l,
                "adj_c": adj_c,
                "va": as_float(row.get("Va")) or 0.0,
                "vo": as_float(row.get("Vo")) or 0.0,
            }
        days = sorted(cleaned)
        return cls(
            code=code,
            dates=days,
            raw_o=[cleaned[d]["raw_o"] for d in days],
            raw_h=[cleaned[d]["raw_h"] for d in days],
            raw_l=[cleaned[d]["raw_l"] for d in days],
            raw_c=[cleaned[d]["raw_c"] for d in days],
            adj_o=[cleaned[d]["adj_o"] for d in days],
            adj_h=[cleaned[d]["adj_h"] for d in days],
            adj_l=[cleaned[d]["adj_l"] for d in days],
            adj_c=[cleaned[d]["adj_c"] for d in days],
            va=[cleaned[d]["va"] for d in days],
            vo=[cleaned[d]["vo"] for d in days],
            loc={d: i for i, d in enumerate(days)},
        )

    def at(self, day: date) -> int | None:
        return self.loc.get(day)

    def bad(self, index: int) -> bool:
        return (
            self.adj_o[index] <= 0
            or self.adj_c[index] <= 0
            or self.raw_o[index] <= 0
            or self.adj_h[index] < self.adj_l[index]
        )

    def ret_n(self, day: date, n: int) -> float | None:
        index = self.loc.get(day)
        if index is None or index < n:
            return None
        prev = self.adj_c[index - n]
        cur = self.adj_c[index]
        if prev <= 0 or cur <= 0:
            return None
        return cur / prev - 1.0

    def daily_ret(self, day: date) -> float | None:
        return self.ret_n(day, 1)

    def ma(self, day: date, n: int) -> float | None:
        index = self.loc.get(day)
        if index is None or index + 1 < n:
            return None
        window = self.adj_c[index + 1 - n : index + 1]
        if any(price <= 0 for price in window):
            return None
        return sum(window) / n

    def vol_change(self, day: date, n: int = 20) -> float | None:
        index = self.loc.get(day)
        if index is None or index < n:
            return None
        base = self.vo[index - n : index]
        if not base or sum(base) <= 0:
            return None
        return self.vo[index] / (sum(base) / len(base)) - 1.0

    def close_asof(self, day: date) -> float | None:
        pos = bisect.bisect_right(self.dates, day) - 1
        if pos < 0:
            return None
        price = self.adj_c[pos]
        return price if price > 0 else None


@dataclass(frozen=True)
class Listing:
    code: str
    name: str
    mkt: str
    prod: str
    sector: str
    scale: str


class MasterBook:
    def __init__(self, snapshots: list[tuple[date, dict[str, Listing]]]) -> None:
        ordered = sorted(snapshots, key=lambda item: item[0])
        self.days = [day for day, _ in ordered]
        self.rows = [rows for _, rows in ordered]

    def asof(self, day: date) -> dict[str, Listing]:
        if not self.days:
            return {}
        pos = bisect.bisect_right(self.days, day) - 1
        if pos < 0:
            return {}
        return self.rows[pos]


@dataclass
class Panel:
    clock: list[date]
    series: dict[str, Series]
    benchmark_code: str

    def bench(self) -> Series:
        return self.series[self.benchmark_code]

    def anomaly_counts(self) -> dict[str, int]:
        bars = 0
        bad = 0
        for series in self.series.values():
            for index in range(len(series.dates)):
                bars += 1
                if series.bad(index):
                    bad += 1
        return {"bars": bars, "bad_bars": bad, "names": len(self.series)}
