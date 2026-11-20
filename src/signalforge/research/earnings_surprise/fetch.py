"""Cached J-Quants downloads for the earnings-surprise study.

The API key is read from the environment or `.env` and is never written out.
Files already on disk are kept, so a rerun resumes.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from pathlib import Path

import polars as pl
from dotenv import load_dotenv

from signalforge.alt_data.jquants_client import JQuantsError, get_paginated
from signalforge.research.earnings_surprise.config import BENCHMARK_CODE, REQUESTED_YEARS
from signalforge.research.earnings_surprise.panel import Listing, MasterBook, Panel, Series, as_date, as_float

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data" / "earnings_surprise"
BARS = DATA / "bars"
FINS = DATA / "fins"
MASTERS = DATA / "master"

BAR_FLOATS = ("O", "H", "L", "C", "Vo", "Va", "AdjO", "AdjH", "AdjL", "AdjC")
FIN_FLOATS = ("Sales", "OP", "OdP", "NP", "EPS", "FSales", "FOP", "FOdP", "FNP", "FEPS")
FIN_STRINGS = ("Code", "DiscDate", "DiscTime", "DiscNo", "DocType", "CurPerType", "CurPerEn", "CurFYEn")


def _pace(min_interval: float, nxt: list[float]) -> None:
    now = time.monotonic()
    if now < nxt[0]:
        time.sleep(nxt[0] - now)
    nxt[0] = time.monotonic() + min_interval


def _shifted_window(exc: Exception) -> tuple[date, date] | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", str(exc))
    if match is None:
        return None
    return date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2))


def _save_window(start: date, end: date) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "window.json").write_text(
        json.dumps({"plan_start": start.isoformat(), "plan_end": end.isoformat()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def plan_window() -> tuple[date, date]:
    load_dotenv(ROOT / ".env")
    cached = DATA / "window.json"
    if cached.exists():
        payload = json.loads(cached.read_text(encoding="utf-8"))
        return date.fromisoformat(payload["plan_start"]), date.fromisoformat(payload["plan_end"])
    try:
        get_paginated(
            "/equities/bars/daily",
            {"code": "72030", "from": "2019-01-01", "to": "2019-01-10"},
            max_pages=1,
        )
    except JQuantsError as exc:
        shifted = _shifted_window(exc)
        if shifted is None:
            raise
        _save_window(*shifted)
        return shifted
    raise RuntimeError("プラン期間の上限を応答から読めませんでした。")


def _write_frame(rows: list[dict], path: Path, strings: tuple[str, ...], floats: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        schema = {name: pl.Utf8 for name in strings}
        schema.update({name: pl.Float64 for name in floats})
        pl.DataFrame(schema=schema).write_parquet(path)
        return
    slim = []
    for row in rows:
        item = {name: "" if row.get(name) is None else str(row.get(name)) for name in strings}
        for name in floats:
            item[name] = as_float(row.get(name))
        slim.append(item)
    frame = pl.DataFrame(slim)
    string_casts = [pl.col(name).cast(pl.Utf8) for name in strings if name in frame.columns]
    float_casts = [pl.col(name).cast(pl.Float64, strict=False) for name in floats if name in frame.columns]
    if string_casts:
        frame = frame.with_columns(string_casts)
    if float_casts:
        frame = frame.with_columns(float_casts)
    frame.write_parquet(path)


def _fetch_rows(path: str, params: dict, min_interval: float, nxt: list[float]) -> list[dict]:
    for attempt in range(6):
        _pace(min_interval, nxt)
        try:
            return get_paginated(path, params)
        except JQuantsError as exc:
            if "429" not in str(exc) or attempt == 5:
                raise
            wait = 20 * (attempt + 1)
            print(f"429 wait {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"unreachable fetch {path}")


def fetch_sample(n: int = 100, *, rpm: float = 8.0) -> dict[str, str]:
    """Download the benchmark, month-end masters, and the n most liquid prime names.

    Liquidity is ranked on the first session in the plan window, not on later
    returns. Sector indexes built from this cache are not the full prime market.
    """
    load_dotenv(ROOT / ".env")
    interval = 60.0 / rpm
    nxt = [0.0]
    start, end = plan_window()
    DATA.mkdir(parents=True, exist_ok=True)
    bench_path = BARS / f"{BENCHMARK_CODE}.parquet"
    if not bench_path.exists():
        rows = _fetch_rows(
            "/equities/bars/daily",
            {"code": BENCHMARK_CODE, "from": start.isoformat(), "to": end.isoformat()},
            interval,
            nxt,
        )
        _write_frame(rows, bench_path, ("Date", "Code"), BAR_FLOATS)
    clock = sorted({as_date(row.get("Date")) for row in _read(bench_path)})
    clock = [day for day in clock if day is not None]
    if not clock:
        raise RuntimeError("ベンチマークの日足が空です。")
    month_ends: list[date] = []
    seen: set[str] = set()
    for day in clock:
        key = day.strftime("%Y-%m")
        if key in seen:
            month_ends[-1] = day
        else:
            seen.add(key)
            month_ends.append(day)
    master_days = [clock[0], *month_ends]
    for day in master_days:
        path = MASTERS / f"{day.strftime('%Y%m%d')}.parquet"
        if path.exists():
            continue
        try:
            rows = _fetch_rows("/equities/master", {"date": day.isoformat()}, interval, nxt)
        except JQuantsError as exc:
            print(f"master {day.isoformat()} skipped {exc}", flush=True)
            if "429" in str(exc):
                break
            continue
        if not rows:
            print(f"master {day.isoformat()} empty", flush=True)
            continue
        _write_frame(rows, path, ("Date", "Code", "CoName", "Mkt", "ProdCat", "S33Nm", "ScaleCat"), ())
        print(f"master {day.isoformat()} rows={len(rows)}", flush=True)

    selection_path = DATA / "selection.json"
    if selection_path.exists():
        codes = json.loads(selection_path.read_text(encoding="utf-8"))["codes"]
    else:
        cross = _fetch_rows("/equities/bars/daily", {"date": clock[0].isoformat()}, interval, nxt)
        master = _read(MASTERS / f"{clock[0].strftime('%Y%m%d')}.parquet")
        prime = {
            str(row.get("Code"))
            for row in master
            if str(row.get("Mkt")) == "0111" and str(row.get("ProdCat")) == "011"
        }
        ranked: list[tuple[float, str]] = []
        for row in cross:
            code = str(row.get("Code") or "")
            if code in prime:
                ranked.append((as_float(row.get("Va")) or 0.0, code))
        ranked.sort(reverse=True)
        codes = []
        used: set[str] = set()
        for _, code in ranked:
            if code in used:
                continue
            used.add(code)
            codes.append(code)
            if len(codes) >= n:
                break
        selection_path.write_text(
            json.dumps({"asof": clock[0].isoformat(), "codes": codes}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    codes = list(codes)[:n]
    for index, code in enumerate(codes, start=1):
        bar_path = BARS / f"{code}.parquet"
        fin_path = FINS / f"{code}.parquet"
        if not bar_path.exists():
            try:
                rows = _fetch_rows(
                    "/equities/bars/daily",
                    {"code": code, "from": start.isoformat(), "to": end.isoformat()},
                    interval,
                    nxt,
                )
                if not rows:
                    print(f"bars {code} empty", flush=True)
                    continue
                _write_frame(rows, bar_path, ("Date", "Code"), BAR_FLOATS)
            except (JQuantsError, OSError) as exc:
                shifted = _shifted_window(exc)
                if shifted is not None and shifted != (start, end):
                    start, end = shifted
                    _save_window(start, end)
                    print(f"window {start.isoformat()} {end.isoformat()}", flush=True)
                    try:
                        rows = _fetch_rows(
                            "/equities/bars/daily",
                            {"code": code, "from": start.isoformat(), "to": end.isoformat()},
                            interval,
                            nxt,
                        )
                        if rows:
                            _write_frame(rows, bar_path, ("Date", "Code"), BAR_FLOATS)
                            rows = None
                    except (JQuantsError, OSError) as retry_exc:
                        print(f"bars {code} failed {retry_exc}", flush=True)
                        continue
                    if rows is not None and not rows:
                        print(f"bars {code} empty", flush=True)
                        continue
                else:
                    print(f"bars {code} failed {exc}", flush=True)
                    continue
        if not fin_path.exists():
            try:
                rows = _fetch_rows("/fins/summary", {"code": code}, interval, nxt)
                _write_frame(rows, fin_path, FIN_STRINGS, FIN_FLOATS)
            except (JQuantsError, OSError) as exc:
                print(f"fins {code} failed {exc}", flush=True)
                continue
        if index % 10 == 0 or index == len(codes):
            print(f"sample {index}/{len(codes)}", flush=True)
    note = {
        "mode": "sample",
        "plan_start": start.isoformat(),
        "plan_end": end.isoformat(),
        "fetch_start": clock[0].isoformat(),
        "fetch_end": clock[-1].isoformat(),
        "requested_years": str(REQUESTED_YEARS),
        "names": str(len(codes)),
        "benchmark": BENCHMARK_CODE,
        "consensus": "未取得",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (DATA / "meta.json").write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
    return note


def fetch_codes(codes: list[str]) -> None:
    """Download bars and summaries for an explicit code list, plus the benchmark."""
    load_dotenv(ROOT / ".env")
    start, end = plan_window()
    interval = 60.0 / 8.0
    nxt = [0.0]
    for code in [BENCHMARK_CODE, *codes]:
        path = BARS / f"{code}.parquet"
        if path.exists():
            continue
        rows = _fetch_rows(
            "/equities/bars/daily",
            {"code": code, "from": start.isoformat(), "to": end.isoformat()},
            interval,
            nxt,
        )
        if not rows:
            print(f"bars {code} empty", flush=True)
            continue
        _write_frame(rows, path, ("Date", "Code"), BAR_FLOATS)
        print(f"bars {code} {len(rows)}", flush=True)
    clock = [day for day in (as_date(row.get("Date")) for row in _read(BARS / f"{BENCHMARK_CODE}.parquet")) if day]
    clock = sorted(set(clock))
    if clock:
        master_path = MASTERS / f"{clock[0].strftime('%Y%m%d')}.parquet"
        if not master_path.exists():
            rows = _fetch_rows("/equities/master", {"date": clock[0].isoformat()}, interval, nxt)
            _write_frame(rows, master_path, ("Date", "Code", "CoName", "Mkt", "ProdCat", "S33Nm", "ScaleCat"), ())
    for code in codes:
        path = FINS / f"{code}.parquet"
        if path.exists():
            continue
        rows = _fetch_rows("/fins/summary", {"code": code}, interval, nxt)
        _write_frame(rows, path, FIN_STRINGS, FIN_FLOATS)
        print(f"fins {code} {len(rows)}", flush=True)


def _read(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return pl.read_parquet(path).to_dicts()


def load_cache() -> tuple[Panel, MasterBook, list[dict], dict]:
    bench_path = BARS / f"{BENCHMARK_CODE}.parquet"
    if not bench_path.exists():
        raise RuntimeError("キャッシュがありません。先に fetch-sample か inspect を実行してください。")
    series: dict[str, Series] = {}
    for path in sorted(BARS.glob("*.parquet")):
        rows = _read(path)
        if not rows:
            continue
        code = path.stem
        series[code] = Series.from_rows(code, rows)
    if BENCHMARK_CODE not in series or not series[BENCHMARK_CODE].dates:
        raise RuntimeError("ベンチマークの日足が読めません。")
    clock = list(series[BENCHMARK_CODE].dates)
    snapshots: list[tuple[date, dict[str, Listing]]] = []
    for path in sorted(MASTERS.glob("*.parquet")):
        rows = _read(path)
        if not rows:
            continue
        day = as_date(rows[0].get("Date")) or as_date(path.stem)
        if day is None:
            continue
        mapped: dict[str, Listing] = {}
        for row in rows:
            code = str(row.get("Code") or "")
            if not code:
                continue
            mapped[code] = Listing(
                code=code,
                name=str(row.get("CoName") or code),
                mkt=str(row.get("Mkt") or ""),
                prod=str(row.get("ProdCat") or ""),
                sector=str(row.get("S33Nm") or ""),
                scale=str(row.get("ScaleCat") or ""),
            )
        snapshots.append((day, mapped))
    fins: list[dict] = []
    for path in sorted(FINS.glob("*.parquet")):
        fins.extend(_read(path))
    meta_path = DATA / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta.setdefault("fetch_start", clock[0].isoformat())
    meta.setdefault("fetch_end", clock[-1].isoformat())
    meta["names"] = str(len(series) - (1 if BENCHMARK_CODE in series else 0))
    panel = Panel(clock=clock, series=series, benchmark_code=BENCHMARK_CODE)
    return panel, MasterBook(snapshots), fins, meta
