"""採用ルールで流動性ユニバース全銘柄をランキングし、公開用 JSON を書く。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.config import data_dir
from signalforge.research.trend_screen.frequency import primary_mask
from signalforge.research.trend_screen.horse import _clean, _load_bars
from signalforge.research.trend_screen.improve import _stats_at
from signalforge.research.trend_screen.ruleset import SystemRules, load_adopted, rules_markdown
from signalforge.research.trend_screen.system import _signal_coverage, latest_signal_day
from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

GATE_LABELS = {
    "primary": "一次条件（長期トレンド）",
    "no_bar": "シグナル日の日足なし",
    "above_ma200": "終値>200日線",
    "ma200_up": "200日線上向き",
    "ma75_up": "75日線上向き",
    "ret_1y_pos": "1年リターン>0",
    "ret_3y_pos": "3年リターン>0",
    "excess_1y": "1年でTOPIX超え",
    "turnover": "売買代金下限",
    "ret_20d": "直近20日下落なし",
    "above_ma25": "終値>25日線",
    "dd_52w": "52週高値からの下落上限",
}


def published_ranking_path() -> Path:
    return data_dir() / "published" / "trend_screen_ranking.json"


def _listing_maps() -> tuple[dict[str, dict], dict[str, str]]:
    from signalforge.universe.tse_listing import listing_by_ticker

    try:
        listing = listing_by_ticker()
    except Exception:
        return {}, {}
    sectors = {str(sym): str(row.get("sector_tse") or "未確認") for sym, row in listing.items()}
    return listing, sectors


def _passes_extra(rules: SystemRules, stats: dict[str, float | None]) -> tuple[bool, list[str]]:
    fails: list[str] = []
    if rules.min_turnover is not None:
        turn = stats.get("turnover_20d")
        if turn is None or turn < rules.min_turnover:
            fails.append("turnover")
    if rules.min_ret_20d is not None:
        ret20 = stats.get("ret_20d")
        if ret20 is None or ret20 <= rules.min_ret_20d:
            fails.append("ret_20d")
    if rules.require_above_ma25:
        vs25 = stats.get("vs_ma25")
        if vs25 is None or vs25 <= 0:
            fails.append("above_ma25")
    if rules.max_dd_52w is not None:
        dd52 = stats.get("dd_52w")
        if dd52 is None or dd52 < rules.max_dd_52w:
            fails.append("dd_52w")
    return not fails, fails


def build_ranking(*, limit: int | None = None, refresh_universe: bool = True) -> dict[str, Any]:
    rules = load_adopted()
    limit = limit or rules.universe_limit
    if refresh_universe:
        write_liquid_list(limit)
    names = read_liquid_list(limit)
    closes, volumes, bench = _load_bars(names)
    bench = _clean(bench)
    signal = latest_signal_day(bench)
    n_on_signal, coverage_ok, warning = _signal_coverage(closes, signal)
    listing, sectors = _listing_maps()

    rows: list[dict[str, Any]] = []
    for code, series in closes.items():
        px = _clean(series)
        had_bar = signal in px.index
        mask = primary_mask(series, bench)
        mask_ok = bool(had_bar and signal in mask.index and bool(mask.loc[signal]))
        stats = _stats_at(series, volumes.get(code), signal) if had_bar else {
            "ret_1y": None,
            "vol_1y": None,
            "risk_adj_1y": None,
            "turnover_20d": None,
            "ret_20d": None,
            "vs_ma25": None,
            "dd_52w": None,
        }
        extra_ok, extra_fails = _passes_extra(rules, stats)
        passed = bool(mask_ok and extra_ok and stats.get("ret_1y") is not None)
        fails = ([] if mask_ok else ["primary"]) + extra_fails
        if not had_bar:
            fails = ["no_bar"]
        sym = code.replace(".T", "")
        meta = listing.get(code) or listing.get(sym) or {}
        price = float(px.loc[signal]) if had_bar else None
        rows.append(
            {
                "ticker": code,
                "code": sym,
                "name": str(meta.get("name") or ""),
                "sector": sectors.get(code) or sectors.get(sym) or str(meta.get("sector_tse") or ""),
                "market": str(meta.get("market") or meta.get("segment") or ""),
                "passed": passed,
                "fails": fails,
                "fail_labels": [GATE_LABELS.get(f, f) for f in fails],
                "price": price,
                "ret_1y": stats.get("ret_1y"),
                "ret_20d": stats.get("ret_20d"),
                "dd_52w": stats.get("dd_52w"),
                "vs_ma25": stats.get("vs_ma25"),
                "vol_1y": stats.get("vol_1y"),
                "turnover_20d": stats.get("turnover_20d"),
            }
        )

    passers = [r for r in rows if r["passed"]]
    passers.sort(key=lambda r: (-(r["ret_1y"] or -1e9), r["code"]))
    for i, row in enumerate(passers, start=1):
        row["rank"] = i
        row["target"] = i <= int(rules.top_n)

    others = [r for r in rows if not r["passed"]]
    others.sort(
        key=lambda r: (
            0 if r["fails"] == ["primary"] else 1,
            len(r["fails"]),
            -(r["ret_1y"] if r["ret_1y"] is not None else -1e9),
            r["code"],
        )
    )
    for row in others:
        row["rank"] = None
        row["target"] = False

    targets = [
        {
            "rank": r["rank"],
            "ticker": r["ticker"],
            "code": r["code"],
            "name": r["name"],
            "weight": 1.0 / min(rules.top_n, len(passers)) if passers else 0.0,
            "ret_1y": r["ret_1y"],
            "ret_20d": r["ret_20d"],
            "price": r["price"],
        }
        for r in passers[: rules.top_n]
    ]

    payload: dict[str, Any] = {
        "system_id": rules.id,
        "version": rules.version,
        "name": rules.name,
        "signal_date": signal.date().isoformat(),
        "benchmark": rules.benchmark,
        "universe_limit": limit,
        "n_universe": len(closes),
        "n_on_signal": n_on_signal,
        "n_pass": len(passers),
        "n_target": len(targets),
        "coverage_ok": coverage_ok,
        "warning": warning,
        "top_n": rules.top_n,
        "rank_by": rules.rank_by,
        "min_turnover": rules.min_turnover,
        "min_ret_20d": rules.min_ret_20d,
        "require_above_ma25": rules.require_above_ma25,
        "max_dd_52w": rules.max_dd_52w,
        "rules_markdown": rules_markdown(rules),
        "targets": targets,
        "ranking": passers,
        "rejected": others,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    return payload


def save_ranking(payload: dict[str, Any], path: Path | None = None) -> Path:
    path = path or published_ranking_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_ranking(path: Path | None = None) -> dict[str, Any] | None:
    path = path or published_ranking_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def build_and_publish(*, limit: int | None = None) -> tuple[dict[str, Any], Path]:
    payload = build_ranking(limit=limit)
    path = save_ranking(payload)
    return payload, path
