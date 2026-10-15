"""Per-ticker earnings / ex-div dates via yfinance (best-effort for *.T)."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import Any

import pandas as pd

from signalforge.alt_data.paths import earnings_path


def _parse_dates(raw: Any) -> list[str]:
    out: list[str] = []
    if raw is None:
        return out
    if isinstance(raw, list):
        for x in raw:
            out.extend(_parse_dates(x))
        return out
    if isinstance(raw, (datetime, date)):
        return [raw.isoformat()[:10]]
    s = str(raw).strip()
    if len(s) >= 10 and s[4] == "-":
        return [s[:10]]
    return out


def fetch_earnings_dates(ticker: str, *, sleep_s: float = 0.15) -> list[str]:
    import yfinance as yf

    time.sleep(sleep_s)
    tk = yf.Ticker(ticker)
    dates: list[str] = []
    cal = getattr(tk, "calendar", None)
    if isinstance(cal, dict):
        dates.extend(_parse_dates(cal.get("Earnings Date")))
        dates.extend(_parse_dates(cal.get("Ex-Dividend Date")))
    try:
        edf = tk.get_earnings_dates(limit=24)
        if edf is not None and not getattr(edf, "empty", True):
            for ts in edf.index:
                dates.append(pd_timestamp_to_iso(ts))
    except Exception:
        pass
    uniq = sorted({d for d in dates if d})
    return uniq


def pd_timestamp_to_iso(ts: Any) -> str:
    t = pd.Timestamp(ts)
    if t.tz is not None:
        t = t.tz_convert(None)
    return t.strftime("%Y-%m-%d")


def save_earnings(ticker: str, dates: list[str]) -> None:
    path = earnings_path(ticker)
    path.write_text(
        json.dumps({"ticker": ticker, "event_dates": dates, "source": "yfinance"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_earnings(ticker: str) -> list[str]:
    path = earnings_path(ticker)
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    raw = doc.get("event_dates") or doc.get("earnings_dates") or []
    return [str(d)[:10] for d in raw if d]


def fetch_earnings_universe(
    tickers: list[str],
    *,
    refresh: bool = False,
    progress_cb=None,
) -> dict[str, int]:
    ok = 0
    for i, sym in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, len(tickers), sym)
        path = earnings_path(sym)
        if path.exists() and not refresh:
            ok += 1
            continue
        dates = fetch_earnings_dates(sym)
        save_earnings(sym, dates)
        if dates:
            ok += 1
    return {"tickers": len(tickers), "with_dates": ok}
