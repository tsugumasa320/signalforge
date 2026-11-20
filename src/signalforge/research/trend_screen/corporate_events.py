"""決算・配当・優待の参考表示用メトリクス。スクリーニング通過条件には使わない。"""

from __future__ import annotations

import csv
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from signalforge.alt_data.earnings import load_earnings
from signalforge.alt_data.paths import dividends_path, yutai_list_path, yutai_meguri_stats_path

YUTAI_CSV_URL = "https://yutai-shirabe.com/download/yutai-list.csv"
YUTAI_MEGURI_CSV_URL = "https://yutai-meguri.com/stats/stock-stats.csv"
YAHOO_JP_QUOTE = "https://finance.yahoo.co.jp/quote/{ticker}"
_YUTAI_UNKNOWN_TYPES = frozenset({"", "記載なし", "読み取れず", "不明"})

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


def _download_csv(url: str, path: Path, *, max_age_days: int, force: bool) -> Path:
    if path.exists() and not force:
        age = (_parse_as_of(None) - datetime.fromtimestamp(path.stat().st_mtime).date()).days
        if age <= max_age_days and path.stat().st_size > 200:
            return path
    with urlopen(url, timeout=60) as resp:
        path.write_bytes(resp.read())
    return path


def ensure_yutai_list(*, max_age_days: int = 7, force: bool = False) -> Path:
    return _download_csv(YUTAI_CSV_URL, yutai_list_path(), max_age_days=max_age_days, force=force)


def ensure_yutai_meguri_stats(*, max_age_days: int = 7, force: bool = False) -> Path:
    return _download_csv(
        YUTAI_MEGURI_CSV_URL,
        yutai_meguri_stats_path(),
        max_age_days=max_age_days,
        force=force,
    )


def _parse_month_nums(text: str | None) -> list[int]:
    if not text:
        return []
    seen: set[int] = set()
    out: list[int] = []
    for m in re.findall(r"(\d{1,2})", str(text)):
        n = int(m)
        if 1 <= n <= 12 and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _format_yutai_months(months: list[int]) -> str | None:
    if not months:
        return None
    return "・".join(f"{m}月" for m in months)


def _merge_yutai_months(*texts: str | None) -> str | None:
    merged: list[int] = []
    seen: set[int] = set()
    for text in texts:
        for m in _parse_month_nums(text):
            if m not in seen:
                seen.add(m)
                merged.append(m)
    return _format_yutai_months(sorted(merged))


def _clean_yutai_type(raw: str | None) -> str | None:
    text = (raw or "").strip() or None
    if text is None or text in _YUTAI_UNKNOWN_TYPES:
        return None
    return text


def _load_meguri_supplement(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """優待めぐり（店舗優待寄り）で権利月・必要株数を補完する。"""
    try:
        path = ensure_yutai_meguri_stats(force=refresh)
    except Exception:
        return {}
    if not path.exists() or path.stat().st_size < 40:
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    for row in csv.DictReader(text.splitlines()):
        code = str(row.get("証券コード") or "").strip()
        if not code:
            continue
        months = _format_yutai_months(_parse_month_nums(row.get("権利確定月")))
        min_raw = row.get("必要株数(最低)") or row.get("必要株数")
        try:
            min_shares = int(float(min_raw)) if str(min_raw or "").strip() else None
        except (TypeError, ValueError):
            min_shares = None
        out[code] = {
            "yutai_months": months,
            "yutai_min_shares": min_shares,
        }
    return out


def load_yutai_map(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """優待しらべを主、優待めぐりで権利月・必要株数を突合したマップ。"""
    path = ensure_yutai_list(force=refresh)
    out: dict[str, dict[str, Any]] = {}
    text = path.read_text(encoding="utf-8-sig")
    for row in csv.DictReader(text.splitlines()):
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
        ytype = _clean_yutai_type(row.get("優待の種類"))
        months = _format_yutai_months(_parse_month_nums(row.get("権利確定月")))
        out[code] = {
            "yutai": True,
            "yutai_months": months,
            "yutai_record": (row.get("基準日") or "").strip() or None,
            "yutai_min_shares": min_shares_i,
            "yutai_type": ytype,
            "yutai_annual_est": annual_i,
            "yutai_url": (row.get("会社ページのURL") or "").strip() or None,
        }

    meguri = _load_meguri_supplement(refresh=refresh)
    for code, extra in meguri.items():
        if code in out:
            base = out[code]
            base["yutai_months"] = _merge_yutai_months(
                base.get("yutai_months"),
                extra.get("yutai_months"),
            )
            if base.get("yutai_min_shares") is None and extra.get("yutai_min_shares") is not None:
                base["yutai_min_shares"] = extra["yutai_min_shares"]
            continue
        # しらべに無いがめぐりにある銘柄は「あり」のみ（種類は不明）
        out[code] = {
            "yutai": True,
            "yutai_months": extra.get("yutai_months"),
            "yutai_record": None,
            "yutai_min_shares": extra.get("yutai_min_shares"),
            "yutai_type": None,
            "yutai_annual_est": None,
            "yutai_url": f"https://yutai-shirabe.com/c/{code}.html",
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
