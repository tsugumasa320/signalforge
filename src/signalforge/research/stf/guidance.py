"""Company-forecast revisions, visible only after the announcement.

A change is an increase or decrease in full-year net-profit guidance (FNP)
against the previous disclosure of the same fiscal year. Consolidated
figures are used when the company publishes them. A jump of 1000x or more
is treated as a unit break and does not count as a revision.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from signalforge.research.stf.rules import GUIDANCE_LOOKBACK

FINS = Path(__file__).resolve().parents[4] / "data" / "stf" / "fins"


@dataclass(frozen=True)
class Disclosure:
    code: str
    disc_date: date
    disc_time: str
    consol: str
    fiscal_end: str
    fnp: float | None


def consol_flag(doc_type: str) -> str:
    return "noncons" if "NonConsolidated" in (doc_type or "") else "cons"


def parse_fnp(value: object) -> float | None:
    if value is None:
        return None
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


def known_on(disc_date: date, disc_time: str, sessions: list[date]) -> date | None:
    """First session whose close can reflect the announcement."""
    before_close = bool(disc_time) and disc_time < "15:00:00"
    if before_close:
        pos = bisect.bisect_left(sessions, disc_date)
    else:
        pos = bisect.bisect_right(sessions, disc_date)
    if pos >= len(sessions):
        return None
    return sessions[pos]


def _changes(rows: list[Disclosure], sessions: list[date]) -> list[tuple[date, str]]:
    rows = sorted(rows, key=lambda row: (row.disc_date, row.disc_time))
    last_fy: str | None = None
    last_fnp: float | None = None
    out: list[tuple[date, str]] = []
    for row in rows:
        if row.fiscal_end != last_fy:
            last_fy = row.fiscal_end
            last_fnp = row.fnp
            continue
        if row.fnp is None or last_fnp is None:
            if row.fnp is not None:
                last_fnp = row.fnp
            continue
        ratio = abs(row.fnp / last_fnp) if last_fnp != 0.0 else None
        known = known_on(row.disc_date, row.disc_time, sessions)
        if ratio is None or ratio >= 1000.0 or ratio <= 0.001:
            last_fnp = row.fnp
            last_fy = row.fiscal_end
            continue
        if known is not None and row.fnp > last_fnp:
            out.append((known, "up"))
        elif known is not None and row.fnp < last_fnp:
            out.append((known, "down"))
        last_fnp = row.fnp
        last_fy = row.fiscal_end
    return out


def load_disclosures() -> list[Disclosure]:
    files = sorted(FINS.glob("*.parquet"))
    if not files:
        raise RuntimeError("決算短信がありません。`python -m signalforge.research.stf fins` を先に実行してください。")
    frame = pl.concat([pl.read_parquet(path) for path in files], how="diagonal")
    out: list[Disclosure] = []
    for row in frame.iter_rows(named=True):
        code = row.get("Code")
        raw_date = row.get("DiscDate")
        if not code or not raw_date:
            continue
        out.append(
            Disclosure(
                code=str(code),
                disc_date=date.fromisoformat(str(raw_date)[:10]),
                disc_time=str(row.get("DiscTime") or ""),
                consol=consol_flag(str(row.get("DocType") or "")),
                fiscal_end=str(row.get("CurFYEn") or ""),
                fnp=parse_fnp(row.get("FNP")),
            )
        )
    return out


def revision_map(
    disclosures: list[Disclosure],
    sessions: list[date],
    asofs: list[date],
    *,
    lookback: int = GUIDANCE_LOOKBACK,
) -> dict[date, dict[str, str]]:
    """Latest up/down guidance change still inside ``lookback`` sessions."""
    grouped: dict[tuple[str, str], list[Disclosure]] = {}
    has_consol: set[str] = set()
    for row in disclosures:
        grouped.setdefault((row.code, row.consol), []).append(row)
        if row.consol == "cons":
            has_consol.add(row.code)
    changes: dict[str, list[tuple[date, str]]] = {}
    for (code, consol), rows in grouped.items():
        if consol == "noncons" and code in has_consol:
            continue
        found = _changes(rows, sessions)
        if found:
            changes[code] = found
    index = {day: i for i, day in enumerate(sessions)}
    result = {day: {} for day in asofs}
    for code, items in changes.items():
        items.sort()
        cursor = 0
        for day in sorted(asofs):
            while cursor < len(items) and items[cursor][0] <= day:
                cursor += 1
            if cursor == 0:
                continue
            known, direction = items[cursor - 1]
            if day not in index or known not in index:
                continue
            if index[day] - index[known] <= lookback:
                result[day][code] = direction
    return result
