"""Build a point-in-time panel from the on-disk J-Quants cache."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import polars as pl

from signalforge.research.stf.engine import Panel
from signalforge.research.stf.fetch import DATA
from signalforge.research.stf.rules import (
    BENCHMARK_CODE,
    COMMON_STOCK,
    MIN_WARM_NAMES,
    TSE_CASH_MARKETS,
)
from signalforge.research.stf.signals import Snap, compute_indicators


def _date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def load_panel(root: Path | None = None) -> tuple[Panel, dict]:
    data = root or DATA
    bar_files = sorted((data / "bars").glob("*.parquet"))
    master_files = sorted((data / "master").glob("*.parquet"))
    if not bar_files or not master_files:
        raise RuntimeError(f"キャッシュがありません: {data}. 先に fetch を実行してください。")

    print(f"loading {len(bar_files)} bar files", flush=True)
    bars = pl.concat([pl.read_parquet(path) for path in bar_files], how="diagonal_relaxed")
    print(f"bars {bars.height}", flush=True)
    bars = bars.with_columns(
        [
            pl.col("Date").cast(pl.Utf8).str.slice(0, 10).str.to_date().alias("date"),
            pl.col("Code").cast(pl.Utf8).alias("code"),
            pl.coalesce([pl.col("AdjC"), pl.col("C")]).cast(pl.Float64).alias("adj_c"),
            pl.coalesce([pl.col("AdjO"), pl.col("O")]).cast(pl.Float64).alias("adj_o"),
            pl.col("Va").cast(pl.Float64).alias("va"),
            pl.col("C").cast(pl.Float64, strict=False).alias("raw_c"),
        ]
    )
    dup = bars.height - bars.select(["date", "code"]).unique().height
    bars = bars.sort(["code", "date", "Va"], descending=[False, False, True]).unique(
        subset=["date", "code"], keep="first"
    )
    extreme = (
        bars.sort(["code", "date"])
        .with_columns((pl.col("adj_c") / pl.col("adj_c").shift(1).over("code") - 1.0).alias("_r"))
        .filter(pl.col("_r").abs() > 0.5)
        .height
    )

    print("indicators", flush=True)
    indicated = compute_indicators(bars.select(["date", "code", "adj_o", "adj_c", "va", "raw_c"]))
    benchmark: dict[date, float] = {}
    for row in indicated.filter(pl.col("code") == BENCHMARK_CODE).iter_rows(named=True):
        if row["adj_c"] is not None and row["adj_c"] > 0.0:
            benchmark[_date(row["date"])] = float(row["adj_c"])

    universe: dict[date, dict[str, tuple[str, str]]] = {}
    prod_counts: dict[str, int] = {}
    market_counts: dict[str, int] = {}
    for path in master_files:
        master = pl.read_parquet(path)
        day = _date(master["Date"][0]) if master.height else _date(path.stem)
        members: dict[str, tuple[str, str]] = {}
        for row in master.iter_rows(named=True):
            prod = str(row.get("ProdCat") or "")
            market = str(row.get("Mkt") or "")
            prod_counts[prod] = prod_counts.get(prod, 0) + 1
            market_counts[market] = market_counts.get(market, 0) + 1
            code = str(row.get("Code") or "")
            if prod != COMMON_STOCK or market not in TSE_CASH_MARKETS or code == BENCHMARK_CODE:
                continue
            members[code] = (
                str(row.get("CoName") or ""),
                str(row.get("S33Nm") or ""),
                market,
            )
        universe[day] = members

    allowed = set().union(*universe.values()) if universe else set()
    indicated = indicated.filter(pl.col("code").is_in(list(allowed)))

    snaps: dict[date, dict[str, Snap]] = {}
    last_session: dict[str, date] = {}
    last_close: dict[str, float] = {}
    for row in indicated.iter_rows(named=True):
        day = _date(row["date"])
        code = row["code"]
        snap = Snap(
            adj_o=_clean(row.get("adj_o")),
            adj_c=_clean(row.get("adj_c")),
            ret20=_clean(row.get("ret20")),
            ret60=_clean(row.get("ret60")),
            sma25=_clean(row.get("sma25")),
            sma75=_clean(row.get("sma75")),
            sma25_lag5=_clean(row.get("sma25_lag5")),
            sma75_lag5=_clean(row.get("sma75_lag5")),
            adv20=_clean(row.get("adv20")),
            raw_c=_clean(row.get("raw_c")),
        )
        snaps.setdefault(day, {})[code] = snap
        if snap.adj_c is not None and snap.adj_c > 0.0:
            prev = last_session.get(code)
            if prev is None or day > prev:
                last_session[code] = day
                last_close[code] = snap.adj_c

    sessions = sorted(snaps)
    # Toyota calendar is a superset only if we kept every code. Sessions are
    # the dates we actually stored. Prefer the downloaded session list so a
    # halted large-cap day is not invented.
    session_path = data / "sessions.json"
    if session_path.exists():
        import json

        listed = [datetime.strptime(item[:10], "%Y-%m-%d").date() for item in json.loads(session_path.read_text())]
        have = set(sessions)
        sessions = [day for day in listed if day in have]

    tradable: set[date] = set()
    warm_counts: dict[str, int] = {}
    for day, members in universe.items():
        day_snaps = snaps.get(day, {})
        ready = 0
        for code in members:
            snap = day_snaps.get(code)
            if snap is not None and snap.sma75 is not None and snap.ret60 is not None:
                ready += 1
        warm_counts[day.isoformat()] = ready
        if ready >= MIN_WARM_NAMES and day in set(sessions):
            tradable.add(day)

    names = {code: pair[0] for members in universe.values() for code, pair in members.items()}
    month_keys = sorted(universe)
    left: list[str] = []
    if month_keys:
        last_members = set(universe[month_keys[-1]])
        seen: set[str] = set()
        for day in month_keys[:-1]:
            for code in universe[day]:
                if code not in last_members and code not in seen:
                    seen.add(code)
                    left.append(code)

    audit = {
        "bar_rows": bars.height,
        "duplicate_date_code": dup,
        "extreme_abs_return_over_50pct": extreme,
        "sessions": len(sessions),
        "session_start": sessions[0].isoformat() if sessions else None,
        "session_end": sessions[-1].isoformat() if sessions else None,
        "benchmark_days": len(benchmark),
        "benchmark_code": BENCHMARK_CODE,
        "month_ends": {day.isoformat(): len(members) for day, members in sorted(universe.items())},
        "warm_names": warm_counts,
        "tradable_month_ends": sorted(day.isoformat() for day in tradable),
        "names_leaving_master": len(left),
        "names_leaving_sample": [f"{code} {names.get(code, '')}" for code in left[:30]],
        "prod_cat_rows": prod_counts,
        "market_rows": market_counts,
        "null_adj_close": int(bars.filter(pl.col("adj_c").is_null()).height),
    }
    panel = Panel(
        sessions=sessions,
        snaps=snaps,
        universe=universe,
        month_ends=tradable,
        benchmark=benchmark,
        last_session=last_session,
        last_close=last_close,
        names=names,
    )
    return panel, audit


def _clean(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number
