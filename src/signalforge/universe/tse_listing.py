"""Tokyo Stock Exchange listed issues from JPX official Excel (monthly)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import pandas as pd

from signalforge.config import data_dir

JPX_LIST_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
FALLBACK_XLSX = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"

# 市場・商品区分 → compare cohort segment
MARKET_TO_SEGMENT = {
    "プライム（内国株式）": "prime",
    "スタンダード（内国株式）": "standard",
    "グロース（内国株式）": "growth",
}


def _cache_path() -> Path:
    p = data_dir() / "universe"
    p.mkdir(parents=True, exist_ok=True)
    return p / "tse_listing.json"


def discover_xlsx_url() -> str:
    req = Request(JPX_LIST_PAGE, headers={"User-Agent": "SignalForge/0.1"})
    try:
        html = urlopen(req, timeout=60).read().decode("utf-8", errors="replace")
    except URLError:
        return FALLBACK_XLSX
    m = re.search(r'href="(/markets/statistics-equities/misc/[^"]+data_j\.xlsx)"', html)
    if m:
        return f"https://www.jpx.co.jp{m.group(1)}"
    return FALLBACK_XLSX


def _parse_jpx_frame(df: pd.DataFrame) -> list[dict[str, Any]]:
    code_col = "コード" if "コード" in df.columns else df.columns[1]
    name_col = "銘柄名" if "銘柄名" in df.columns else df.columns[2]
    market_col = "市場・商品区分" if "市場・商品区分" in df.columns else None
    sector_col = "33業種区分" if "33業種区分" in df.columns else None

    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        raw = r.get(code_col)
        if pd.isna(raw):
            continue
        code = str(int(raw) if isinstance(raw, (int, float)) else raw).strip()
        if not code.isdigit():
            continue
        code = code.zfill(4)
        sym = f"{code}.T"
        market = str(r.get(market_col, "")) if market_col else ""
        segment = MARKET_TO_SEGMENT.get(market)
        entry: dict[str, Any] = {
            "ticker": sym,
            "code": code,
            "name": str(r.get(name_col, "")).strip(),
            "market": market,
            "segment": segment,
        }
        if sector_col and pd.notna(r.get(sector_col)):
            entry["sector_tse"] = str(r.get(sector_col)).strip()
        rows.append(entry)
    return rows


def refresh_tse_listing(*, include_non_domestic_equity: bool = False) -> dict[str, Any]:
    """Download JPX xlsx and write data/universe/tse_listing.json."""
    url = discover_xlsx_url()
    df = pd.read_excel(url, engine="openpyxl")
    rows = _parse_jpx_frame(df)
    if not include_non_domestic_equity:
        rows = [r for r in rows if r.get("segment") in ("prime", "standard", "growth")]
    doc = {
        "source_url": url,
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "n_tickers": len(rows),
        "tickers": rows,
    }
    _cache_path().write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def load_tse_listing(*, refresh: bool = False) -> dict[str, Any]:
    path = _cache_path()
    if refresh or not path.exists():
        return refresh_tse_listing()
    return json.loads(path.read_text(encoding="utf-8"))


def list_tse_tickers(
    *,
    segments: list[str] | None = None,
    refresh: bool = False,
    ticker_limit: int = 0,
) -> list[str]:
    """All TSE domestic equities (Prime/Standard/Growth) unless segments narrowed."""
    doc = load_tse_listing(refresh=refresh)
    rows = doc.get("tickers") or []
    if segments:
        seg_set = set(segments)
        rows = [r for r in rows if r.get("segment") in seg_set]
    else:
        rows = [r for r in rows if r.get("segment") in ("prime", "standard", "growth")]
    syms = sorted({str(r["ticker"]) for r in rows if r.get("ticker")})
    if ticker_limit > 0:
        syms = syms[:ticker_limit]
    return syms


def listing_by_ticker(refresh: bool = False) -> dict[str, dict[str, Any]]:
    doc = load_tse_listing(refresh=refresh)
    return {r["ticker"]: r for r in doc.get("tickers") or [] if r.get("ticker")}
