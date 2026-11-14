"""決算・配当・優待の参考表示用メトリクス。スクリーニング通過条件には使わない。"""

from __future__ import annotations

import csv
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from signalforge.alt_data.earnings import load_earnings
from signalforge.alt_data.paths import dividends_path, yutai_list_path

YUTAI_CSV_URL = "https://yutai-shirabe.com/download/yutai-list.csv"
YAHOO_JP_QUOTE = "https://finance.yahoo.co.jp/quote/{ticker}"

_EMPTY = {
    "yahoo_jp_url": None,
    "earnings_last": None,
    "earnings_next": None,
    "earnings_next_days": None,
    "dividend_yield": None,
    "ex_dividend_date": None,
    "last_dividend": None,
    "last_dividend_date": None,
    "yutai": False,
    "yutai_months": None,
    "yutai_record": None,
    "yutai_min_shares": None,
    "yutai_type": None,
    "yutai_annual_est": None,
    "yutai_url": None,
}


def yahoo_jp_url(ticker: str) -> str:
    sym = ticker if "." in ticker else f"{ticker}.T"
    return YAHOO_JP_QUOTE.format(ticker=sym)


def _iso(d: date | datetime | str | None) -> str | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    s = str(d).strip()
    return s[:10] if len(s) >= 10 else None


def _parse_as_of(as_of: str | date | None) -> date:
    if isinstance(as_of, date):
        return as_of
    if as_of:
        return date.fromisoformat(str(as_of)[:10])
    return datetime.now(timezone.utc).astimezone().date()


def earnings_around(ticker: str, as_of: str | date | None) -> dict[str, Any]:
    day = _parse_as_of(as_of)
    dates = sorted({d[:10] for d in load_earnings(ticker) if d})
    last = None
    nxt = None
    for d in dates:
        if d <= day.isoformat():
            last = d
        elif nxt is None:
            nxt = d
    nxt_days = None
    if nxt:
        nxt_days = (date.fromisoformat(nxt) - day).days
    return {
        "earnings_last": last,
        "earnings_next": nxt,
        "earnings_next_days": nxt_days,
    }


def _unix_to_iso(v: Any) -> str | None:
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(float(v), tz=timezone.utc).date().isoformat()
        return _iso(v)
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def _dividend_yield_frac(info: dict[str, Any], price: float | None) -> float | None:
    tady = info.get("trailingAnnualDividendYield")
    try:
        if tady is not None:
            x = float(tady)
            if 0 < x < 1.0:
                return x
            if 1.0 <= x <= 40.0:
                return x / 100.0
    except (TypeError, ValueError):
        pass
    dy = info.get("dividendYield")
    try:
        if dy is not None:
            x = float(dy)
            if 0 < x < 1.0:
                return x
            if 1.0 <= x <= 40.0:
                return x / 100.0
    except (TypeError, ValueError):
        pass
    rate = info.get("trailingAnnualDividendRate")
    if rate is None:
        rate = info.get("dividendRate")
    try:
        if rate is not None and price and float(price) > 0:
            return float(rate) / float(price)
    except (TypeError, ValueError):
        pass
    return None


def _load_div_cache(ticker: str, *, max_age_days: int = 7) -> dict[str, Any] | None:
    path = dividends_path(ticker)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    fetched = str(doc.get("fetched_at") or "")[:10]
    if fetched:
        try:
            age = (_parse_as_of(None) - date.fromisoformat(fetched)).days
            if age > max_age_days:
                return None
        except ValueError:
            pass
    return doc


def _save_div_cache(ticker: str, doc: dict[str, Any]) -> None:
    path = dividends_path(ticker)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_dividend_snapshot(ticker: str, *, sleep_s: float = 0.08) -> dict[str, Any]:
    import yfinance as yf

    time.sleep(sleep_s)
    tk = yf.Ticker(ticker)
    info: dict[str, Any] = {}
    try:
        raw = tk.info or {}
        if isinstance(raw, dict):
            info = raw
    except Exception:
        info = {}
    price = None
    try:
        if info.get("regularMarketPrice") is not None:
            price = float(info["regularMarketPrice"])
        elif info.get("currentPrice") is not None:
            price = float(info["currentPrice"])
    except (TypeError, ValueError):
        price = None
    ex_div = _unix_to_iso(info.get("exDividendDate"))
    if not ex_div:
        cal = getattr(tk, "calendar", None)
        if isinstance(cal, dict):
            ex_div = _iso(cal.get("Ex-Dividend Date"))
        elif cal is not None and hasattr(cal, "to_dict"):
            ex_div = _iso(cal.to_dict().get("Ex-Dividend Date"))
    last_div = None
    last_div_date = None
    try:
        divs = tk.dividends
        if divs is not None and len(divs) > 0:
            last_div = float(divs.iloc[-1])
            last_div_date = _iso(divs.index[-1])
    except Exception:
        pass
    if last_div is None and info.get("lastDividendValue") is not None:
        try:
            last_div = float(info["lastDividendValue"])
        except (TypeError, ValueError):
            pass
    if last_div_date is None:
        last_div_date = _unix_to_iso(info.get("lastDividendDate"))
    doc = {
        "ticker": ticker,
        "fetched_at": datetime.now(timezone.utc).astimezone().date().isoformat(),
        "dividend_yield": _dividend_yield_frac(info, price),
        "ex_dividend_date": ex_div,
        "last_dividend": last_div,
        "last_dividend_date": last_div_date,
        "source": "yfinance",
    }
    _save_div_cache(ticker, doc)
    return doc


def dividend_fields(
    ticker: str,
    *,
    refresh: bool = False,
    fetch_if_missing: bool = False,
) -> dict[str, Any]:
    doc = None if refresh else _load_div_cache(ticker, max_age_days=30 if not refresh else 7)
    if doc is None and (refresh or fetch_if_missing):
        try:
            doc = fetch_dividend_snapshot(ticker)
        except Exception:
            doc = {}
    doc = doc or {}
    yld = doc.get("dividend_yield")
    try:
        if yld is not None and float(yld) <= 0:
            yld = None
    except (TypeError, ValueError):
        yld = None
    return {
        "dividend_yield": yld,
        "ex_dividend_date": doc.get("ex_dividend_date"),
        "last_dividend": doc.get("last_dividend"),
        "last_dividend_date": doc.get("last_dividend_date"),
    }


def ensure_yutai_list(*, max_age_days: int = 30, force: bool = False) -> Path:
    path = yutai_list_path()
    if path.exists() and not force:
        age = (_parse_as_of(None) - datetime.fromtimestamp(path.stat().st_mtime).date()).days
        if age <= max_age_days and path.stat().st_size > 1000:
            return path
    with urlopen(YUTAI_CSV_URL, timeout=60) as resp:
        data = resp.read()
    path.write_bytes(data)
    return path


def load_yutai_map(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    path = ensure_yutai_list(force=refresh)
    out: dict[str, dict[str, Any]] = {}
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        code = str(row.get("コード") or "").strip()
        if not code:
            continue
        min_shares = row.get("必要株数")
        annual = row.get("年額の推定（円）")
        try:
            min_shares_i = int(float(min_shares)) if str(min_shares).strip() else None
        except (TypeError, ValueError):
            min_shares_i = None
        try:
            annual_i = int(float(annual)) if str(annual).strip() else None
        except (TypeError, ValueError):
            annual_i = None
        out[code] = {
            "yutai": True,
            "yutai_months": (row.get("権利確定月") or "").strip() or None,
            "yutai_record": (row.get("基準日") or "").strip() or None,
            "yutai_min_shares": min_shares_i,
            "yutai_type": (row.get("優待の種類") or "").strip() or None,
            "yutai_annual_est": annual_i,
            "yutai_url": (row.get("会社ページのURL") or "").strip() or None,
        }
    return out


def empty_event_fields(ticker: str) -> dict[str, Any]:
    out = dict(_EMPTY)
    out["yahoo_jp_url"] = yahoo_jp_url(ticker)
    return out


def event_fields_for(
    ticker: str,
    *,
    as_of: str | date | None,
    yutai_map: dict[str, dict[str, Any]] | None = None,
    refresh_dividends: bool = False,
) -> dict[str, Any]:
    """1銘柄分の表示用フィールド。"""
    out = empty_event_fields(ticker)
    out.update(earnings_around(ticker, as_of))
    out.update(
        dividend_fields(
            ticker,
            refresh=refresh_dividends,
            fetch_if_missing=refresh_dividends,
        )
    )
    code = ticker.replace(".T", "")
    ymap = yutai_map if yutai_map is not None else {}
    if code in ymap:
        out.update(ymap[code])
    else:
        out["yutai"] = False
    return out


def warm_dividend_cache(tickers: list[str], *, max_workers: int = 6) -> dict[str, int]:
    """欠けている／古い配当キャッシュを並列で埋める。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    missing = [t for t in tickers if _load_div_cache(t) is None]
    ok = 0
    fail = 0
    if not missing:
        return {"tickers": len(tickers), "fetched": 0, "ok": 0, "fail": 0}

    def _one(sym: str) -> bool:
        try:
            fetch_dividend_snapshot(sym)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_one, t): t for t in missing}
        for fut in as_completed(futs):
            if fut.result():
                ok += 1
            else:
                fail += 1
    return {"tickers": len(tickers), "fetched": len(missing), "ok": ok, "fail": fail}
