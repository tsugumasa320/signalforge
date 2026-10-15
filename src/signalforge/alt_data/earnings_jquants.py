"""Earnings calendar from J-Quants V2 (Free plan includes /equities/earnings-calendar)."""

from __future__ import annotations

import json
import time
from typing import Any

from signalforge.alt_data.earnings import earnings_path, save_earnings
from signalforge.alt_data.jquants_client import (
    JQuantsError,
    get_paginated,
    ticker_to_jquants_code,
)
from signalforge.universe.tse_listing import list_tse_tickers


def _dates_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for r in rows:
        for key in ("Date", "date", "AnnouncementDate", "announcement_date", "FYEnd", "fy_end"):
            if key in r and r[key]:
                s = str(r[key])[:10]
                if len(s) >= 10 and s[4] == "-":
                    out.append(s)
    return sorted(set(out))


def fetch_earnings_jquants(ticker: str, *, refresh: bool = False) -> list[str]:
    path = earnings_path(ticker)
    if path.exists() and not refresh:
        from signalforge.alt_data.earnings import load_earnings

        return load_earnings(ticker)
    code = ticker_to_jquants_code(ticker)
    rows = get_paginated("/equities/earnings-calendar", {"code": code}, max_pages=5)
    dates = _dates_from_rows(rows)
    save_earnings(
        ticker,
        dates,
    )
    # tag source in file
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["source"] = "jquants_v2/equities/earnings-calendar"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except json.JSONDecodeError:
        pass
    return dates


def fetch_earnings_jquants_universe(
    tickers: list[str] | None = None,
    *,
    refresh: bool = False,
    sleep_s: float = 0.25,
    progress_cb=None,
) -> dict[str, int]:
    tickers = tickers or list_tse_tickers()
    with_dates = 0
    for i, sym in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, len(tickers), sym)
        try:
            dates = fetch_earnings_jquants(sym, refresh=refresh)
            if dates:
                with_dates += 1
        except JQuantsError:
            raise
        except Exception:
            pass
        time.sleep(sleep_s)
    return {"tickers": len(tickers), "with_dates": with_dates}
