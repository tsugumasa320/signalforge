"""Enrich AI packets with earnings / event fields from alt-data cache.

Ranking rows usually already carry ``earnings_next*`` when
``trend-screen ranking`` ran with a populated ``data/alt/earnings`` cache.
When those fields are missing (null ranking, stale publish, or cache filled
later), fall back to ``load_earnings`` via ``earnings_around`` — no live API.
"""

from __future__ import annotations

from typing import Any

EVENT_META_FIELDS = (
    "earnings_last",
    "earnings_next",
    "earnings_next_days",
    "ex_dividend_date",
    "event_data",
)


def _missing_earnings(row: dict[str, Any]) -> bool:
    return row.get("earnings_next") is None and row.get("earnings_next_days") is None


def enrich_event_fields(
    row: dict[str, Any],
    *,
    as_of: str | None = None,
    include_dividend: bool = True,
) -> dict[str, Any]:
    """Fill earnings_* (and cheap ex-dividend) from local alt cache when absent.

    ``event_data`` is one of: ``ranking`` | ``alt_cache`` | ``missing``.
    Never raises; never hits the network.
    """
    out = dict(row)
    ticker = out.get("ticker")
    if not ticker:
        out.setdefault("event_data", "missing")
        return out

    if not _missing_earnings(out):
        out["event_data"] = out.get("event_data") or "ranking"
    else:
        try:
            from signalforge.research.trend_screen.corporate_events import earnings_around

            ev = earnings_around(str(ticker), as_of)
        except Exception:  # noqa: BLE001 — degrade to missing
            ev = {}
        has_any = ev.get("earnings_next") is not None or ev.get("earnings_last") is not None
        if has_any:
            out["earnings_last"] = ev.get("earnings_last")
            out["earnings_next"] = ev.get("earnings_next")
            out["earnings_next_days"] = ev.get("earnings_next_days")
            # Past-only calendar still counts as known (no upcoming in cache).
            out["event_data"] = "alt_cache"
        else:
            out.setdefault("earnings_last", None)
            out.setdefault("earnings_next", None)
            out.setdefault("earnings_next_days", None)
            out["event_data"] = "missing"

    if include_dividend and out.get("ex_dividend_date") is None:
        try:
            from signalforge.research.trend_screen.corporate_events import dividend_fields

            div = dividend_fields(str(ticker), refresh=False, fetch_if_missing=False)
            if div.get("ex_dividend_date"):
                out["ex_dividend_date"] = div.get("ex_dividend_date")
        except Exception:  # noqa: BLE001
            pass

    return out


def enrich_event_rows(
    rows: list[dict[str, Any]],
    *,
    as_of: str | None = None,
    include_dividend: bool = True,
) -> list[dict[str, Any]]:
    return [
        enrich_event_fields(r, as_of=as_of, include_dividend=include_dividend) for r in rows
    ]


def event_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Small summary for packet metadata / docs / tests."""
    n = len(rows)
    with_next = sum(1 for r in rows if r.get("earnings_next") is not None)
    from_cache = sum(1 for r in rows if r.get("event_data") == "alt_cache")
    missing = sum(1 for r in rows if r.get("event_data") == "missing")
    return {
        "n": n,
        "with_earnings_next": with_next,
        "from_alt_cache": from_cache,
        "missing": missing,
    }
