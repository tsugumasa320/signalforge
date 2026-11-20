"""Download J-Quants bars and month-end masters into ``data/stf``.

The API key is read from ``JQUANTS_API_KEY`` and is never printed.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import polars as pl
from dotenv import load_dotenv

from signalforge.research.stf.rules import BENCHMARK_CODE, EVAL_END, WARMUP_START

BASE_URL = "https://api.jquants.com/v2"
_NEXT_REQUEST = 0.0
ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data" / "stf"
BAR_COLUMNS = (
    "Date",
    "Code",
    "O",
    "H",
    "L",
    "C",
    "Vo",
    "Va",
    "AdjFactor",
    "AdjO",
    "AdjH",
    "AdjL",
    "AdjC",
    "UL",
    "LL",
    "ExRT",
)


def _root() -> Path:
    return DATA


def _key() -> str:
    load_dotenv(ROOT / ".env")
    key = (os.getenv("JQUANTS_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("JQUANTS_API_KEY が未設定です。.env か環境変数に置いてください。")
    return key


def _get(path: str, params: dict[str, str], *, timeout: int = 180) -> dict:
    url = f"{BASE_URL}{path}?{urlencode(params)}"
    req = Request(url, headers={"x-api-key": _key()})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pace(min_interval: float) -> None:
    global _NEXT_REQUEST
    now = time.monotonic()
    if now < _NEXT_REQUEST:
        time.sleep(_NEXT_REQUEST - now)
    _NEXT_REQUEST = time.monotonic() + min_interval


def _get_all(path: str, params: dict[str, str], *, min_interval: float, timeout: int = 180) -> list[dict]:
    rows: list[dict] = []
    query = dict(params)
    for _page in range(50):
        body = None
        for attempt in range(6):
            _pace(min_interval)
            try:
                body = _get(path, query, timeout=timeout)
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                if exc.code == 429 and attempt < 5:
                    wait = 15 * (attempt + 1)
                    print(f"429 backoff {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"J-Quants HTTP {exc.code}: {detail}") from exc
            except URLError as exc:
                if attempt < 5:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"J-Quants network error: {exc}") from exc
        assert body is not None
        chunk = body.get("data") or []
        if isinstance(chunk, list):
            rows.extend(row for row in chunk if isinstance(row, dict))
        token = body.get("pagination_key")
        if not token:
            return rows
        query["pagination_key"] = token
    raise RuntimeError(f"pagination did not finish for {path}")


def _parse_window(message: str) -> tuple[date, date] | None:
    import re

    match = re.search(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", message)
    if not match:
        return None
    return date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2))


def plan_window(min_interval: float) -> tuple[date, date]:
    """Return the intersection note: the dates this key is allowed to read."""
    try:
        _get_all(
            "/equities/bars/daily",
            {"code": "72030", "from": WARMUP_START.isoformat(), "to": WARMUP_START.isoformat()},
            min_interval=min_interval,
        )
    except RuntimeError as exc:
        window = _parse_window(str(exc))
        if window is None:
            raise
        return window
    # The probe date was inside the plan. Fall back to a recent known-good span
    # by asking for the requested end as well.
    return WARMUP_START, EVAL_END


def _clamp(start: date, end: date, window: tuple[date, date]) -> tuple[date, date]:
    lo = max(start, window[0])
    hi = min(end, window[1])
    if lo > hi:
        raise RuntimeError(f"requested {start}..{end} does not overlap the API window {window[0]}..{window[1]}")
    return lo, hi


def _write_bars(rows: list[dict], path: Path) -> None:
    slim = [{col: row.get(col) for col in BAR_COLUMNS} for row in rows]
    frame = pl.DataFrame(slim, infer_schema_length=len(slim) or 1)
    casts: list[pl.Expr] = []
    for col in ("Date", "Code", "UL", "LL", "ExRT"):
        if col in frame.columns:
            casts.append(pl.col(col).cast(pl.Utf8))
    for col in ("O", "H", "L", "C", "Vo", "Va", "AdjFactor", "AdjO", "AdjH", "AdjL", "AdjC"):
        if col in frame.columns:
            casts.append(pl.col(col).cast(pl.Float64, strict=False))
    if casts:
        frame = frame.with_columns(casts)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)


def _write_master(rows: list[dict], path: Path) -> None:
    frame = pl.DataFrame(rows, infer_schema_length=5000)
    for col in ("Code", "Date", "Mkt", "ProdCat", "S33", "S33Nm", "MktNm", "CoName"):
        if col in frame.columns:
            frame = frame.with_columns(pl.col(col).cast(pl.Utf8))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)


def fetch_all(*, rpm: float = 20.0, end: date | None = None) -> dict[str, str]:
    """Download sessions, month-end masters, and one cross-section per session.

    Files already on disk are left in place so a rerun resumes.
    """
    interval = 60.0 / rpm
    data = _root()
    data.mkdir(parents=True, exist_ok=True)
    window = plan_window(interval)
    start, stop = _clamp(WARMUP_START, end or date(2026, 8, 15), window)
    note = {
        "plan_start": window[0].isoformat(),
        "plan_end": window[1].isoformat(),
        "fetch_start": start.isoformat(),
        "fetch_end": stop.isoformat(),
        "benchmark": BENCHMARK_CODE,
        "topix_endpoint": "unavailable",
    }
    try:
        _get_all(
            "/indices/bars/daily/topix",
            {"from": start.isoformat(), "to": start.isoformat()},
            min_interval=interval,
        )
        note["topix_endpoint"] = "available"
    except RuntimeError as exc:
        note["topix_endpoint"] = str(exc)[:180]

    probe = _get_all(
        "/equities/bars/daily",
        {"code": "72030", "from": start.isoformat(), "to": stop.isoformat()},
        min_interval=interval,
        timeout=180,
    )
    sessions = sorted({str(row["Date"])[:10] for row in probe if row.get("Date")})
    if not sessions:
        raise RuntimeError("7203 の日足が空です。プラン期間と銘柄コードを確認してください。")
    (data / "sessions.json").write_text(json.dumps(sessions), encoding="utf-8")

    month_ends: list[str] = []
    seen: set[str] = set()
    for session in sessions:
        key = session[:7]
        if key in seen:
            month_ends[-1] = session
        else:
            seen.add(key)
            month_ends.append(session)
    (data / "month_ends.json").write_text(json.dumps(month_ends), encoding="utf-8")

    for session in month_ends:
        path = data / "master" / f"{session.replace('-', '')}.parquet"
        if path.exists():
            continue
        rows = _get_all("/equities/master", {"date": session}, min_interval=interval)
        _write_master(rows, path)
        print(f"master {session} rows={len(rows)}", flush=True)

    done = 0
    for session in sessions:
        path = data / "bars" / f"{session.replace('-', '')}.parquet"
        if path.exists():
            done += 1
            continue
        t0 = time.time()
        rows = _get_all("/equities/bars/daily", {"date": session}, min_interval=interval)
        if not rows:
            raise RuntimeError(f"{session} の日足が空です。キャッシュせずに止めました。")
        _write_bars(rows, path)
        done += 1
        print(f"bars {session} rows={len(rows)} {time.time() - t0:.1f}s ({done}/{len(sessions)})", flush=True)

    note["sessions"] = str(len(sessions))
    note["month_ends"] = str(len(month_ends))
    (data / "fetch_meta.json").write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
    return note


def _iso(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


_SUMMARY_COLUMNS = ("Code", "DiscDate", "DiscTime", "DocType", "CurFYEn", "FNP")


def fetch_summaries(*, rpm: float = 12.0, start: date | None = None, end: date | None = None) -> dict[str, str]:
    """Cache one ``/fins/summary`` cross-section per calendar day. Existing files are kept."""
    from datetime import timedelta

    interval = 60.0 / rpm
    window = plan_window(interval)
    start, end = _clamp(start or window[0], end or window[1], window)
    data = _root() / "fins"
    data.mkdir(parents=True, exist_ok=True)
    day = start
    saved = 0
    skipped = 0
    while day <= end:
        path = data / f"{day.strftime('%Y%m%d')}.parquet"
        if path.exists():
            skipped += 1
            day += timedelta(days=1)
            continue
        rows = _get_all("/fins/summary", {"date": day.strftime("%Y%m%d")}, min_interval=interval)
        slim = [{col: row.get(col) for col in _SUMMARY_COLUMNS} for row in rows]
        if slim:
            frame = pl.DataFrame(slim).with_columns([pl.col(col).cast(pl.Utf8) for col in _SUMMARY_COLUMNS])
        else:
            frame = pl.DataFrame(schema={col: pl.Utf8 for col in _SUMMARY_COLUMNS})
        frame.write_parquet(path)
        saved += 1
        if saved % 20 == 0 or rows:
            print(f"fins {day.isoformat()} rows={len(rows)} saved={saved} skip={skipped}", flush=True)
        day += timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(), "saved": str(saved), "skipped": str(skipped)}
