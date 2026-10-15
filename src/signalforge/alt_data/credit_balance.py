"""Margin trading outstanding from J-Quants → per-ticker series for BT enrichment."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.alt_data.jquants_client import (
    JQuantsError,
    get_paginated,
    listing_code_to_jquants,
    ticker_to_jquants_code,
)
from signalforge.alt_data.paths import alt_data_root
from signalforge.universe.tse_listing import listing_by_ticker, list_tse_tickers


def credit_dir() -> Path:
    p = alt_data_root() / "credit_margin"
    p.mkdir(parents=True, exist_ok=True)
    return p


def credit_path(ticker: str) -> Path:
    return credit_dir() / f"{ticker.replace('/', '_')}.json"


def _normalize_margin_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    date_col = "Date" if "Date" in df.columns else "date"
    if date_col not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df[date_col])
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    long_col = "LongVol" if "LongVol" in df.columns else "long_vol"
    shrt_col = "ShrtVol" if "ShrtVol" in df.columns else "shrt_vol"
    if long_col not in df.columns or shrt_col not in df.columns:
        return pd.DataFrame()
    df["margin_long_vol"] = pd.to_numeric(df[long_col], errors="coerce")
    df["margin_shrt_vol"] = pd.to_numeric(df[shrt_col], errors="coerce")
    total = df["margin_long_vol"] + df["margin_shrt_vol"]
    df["margin_shrt_ratio"] = df["margin_shrt_vol"] / total.replace(0, pd.NA)
    df = df.set_index("date")
    return df[["margin_long_vol", "margin_shrt_vol", "margin_shrt_ratio"]]


def fetch_margin_for_ticker(
    ticker: str,
    *,
    jq_code: str | None = None,
    years_back: int = 8,
    refresh: bool = False,
) -> pd.DataFrame:
    path = credit_path(ticker)
    if path.exists() and not refresh:
        return load_margin_frame(ticker)
    listing = listing_by_ticker().get(ticker) or {}
    code = jq_code or listing_code_to_jquants(str(listing.get("code") or ticker_to_jquants_code(ticker)))
    end = date.today()
    start = end - timedelta(days=365 * years_back)
    rows = get_paginated(
        "/markets/margin-interest",
        {
            "code": code,
            "from": start.strftime("%Y%m%d"),
            "to": end.strftime("%Y%m%d"),
        },
    )
    df = _normalize_margin_rows(rows)
    path.write_text(
        json.dumps(
            {
                "ticker": ticker,
                "jquants_code": code,
                "source": "jquants_v2/markets/margin-interest",
                "rows": rows,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return df


def load_margin_frame(ticker: str) -> pd.DataFrame:
    path = credit_path(ticker)
    if not path.exists():
        return pd.DataFrame()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return pd.DataFrame()
    return _normalize_margin_rows(doc.get("rows") or [])


def fetch_margin_universe(
    tickers: list[str] | None = None,
    *,
    refresh: bool = False,
    sleep_s: float = 0.35,
    progress_cb=None,
) -> dict[str, int]:
    import time

    tickers = tickers or list_tse_tickers()
    ok = 0
    errors = 0
    for i, sym in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, len(tickers), sym)
        path = credit_path(sym)
        if path.exists() and not refresh:
            ok += 1
            continue
        try:
            df = fetch_margin_for_ticker(sym, refresh=True)
            if not df.empty:
                ok += 1
            else:
                errors += 1
        except JQuantsError:
            raise
        except Exception:
            errors += 1
        time.sleep(sleep_s)
    return {"tickers": len(tickers), "with_margin": ok, "errors": errors}
