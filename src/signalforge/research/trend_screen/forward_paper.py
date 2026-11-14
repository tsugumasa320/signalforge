"""採用ルールのフォワード（確認期間〜現在）仮想口座。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.config import data_dir
from signalforge.research.trend_screen.config import ROUND_TRIP_COST
from signalforge.research.trend_screen.frequency import build_masks, monthly_signals, ready_date
from signalforge.research.trend_screen.horse import TEST_START, _clean, _load_bars, _pct, _price
from signalforge.research.trend_screen.improve import _sector_map, _weights, select_names
from signalforge.research.trend_screen.ruleset import load_adopted, rules_markdown
from signalforge.research.trend_screen.system import adopted_spec, latest_signal_day
from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

INITIAL_CASH_JPY = 3_000_000.0


def paper_path() -> Path:
    return data_dir() / "paper" / "trend_screen.json"


def published_forward_path() -> Path:
    return data_dir() / "published" / "trend_screen_forward.json"


def _listing_name(code: str, listing: dict[str, dict]) -> str:
    sym = code.replace(".T", "")
    meta = listing.get(code) or listing.get(sym) or {}
    return str(meta.get("name") or "")


def _window_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    empty = {
        "n_months": 0,
        "n_invested": 0,
        "total_return": None,
        "bench_total": None,
        "excess_total": None,
        "cagr": None,
        "bench_cagr": None,
        "mean_excess": None,
        "max_dd": None,
        "avg_names": None,
        "hit_rate": None,
    }
    if not rows:
        return empty
    equity = 1.0
    bench_eq = 1.0
    peak = 1.0
    max_dd = 0.0
    excesses: list[float] = []
    hits = 0
    names = 0
    for row in rows:
        net = float(row["net"])
        bench = float(row["bench"])
        equity *= 1.0 + net
        bench_eq *= 1.0 + bench
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0)
        excesses.append(net - bench)
        if net - bench > 0:
            hits += 1
        names += int(row["n"])
    n = len(rows)
    return {
        "n_months": n,
        "n_invested": sum(1 for row in rows if int(row["n"]) > 0),
        "total_return": equity - 1.0,
        "bench_total": bench_eq - 1.0,
        "excess_total": (equity / bench_eq - 1.0) if bench_eq > 0 else None,
        "cagr": (equity ** (12.0 / n) - 1.0) if equity > 0 else None,
        "bench_cagr": (bench_eq ** (12.0 / n) - 1.0) if bench_eq > 0 else None,
        "mean_excess": sum(excesses) / n,
        "max_dd": max_dd,
        "avg_names": names / n,
        "hit_rate": hits / n,
    }


def _holdings_for(
    *,
    spec,
    signal: pd.Timestamp,
    entry: pd.Timestamp,
    mark: pd.Timestamp,
    masks,
    closes,
    volumes,
    prepared,
    sectors,
    listing,
) -> tuple[list[dict[str, Any]], dict[str, float], float]:
    chosen = select_names(spec, signal, masks, closes, volumes, sectors)
    weights = _weights(spec, chosen, signal, closes, volumes)
    holdings: list[dict[str, Any]] = []
    gross = 0.0
    live: dict[str, float] = {}
    for code, weight in weights.items():
        series = prepared.get(code)
        if series is None or weight <= 0:
            continue
        start_px = _price(series, entry)
        end_px = _price(series, mark)
        if start_px is None or end_px is None:
            continue
        ret = end_px / start_px - 1.0
        live[code] = weight
        gross += weight * ret
        holdings.append(
            {
                "ticker": code,
                "code": code.replace(".T", ""),
                "name": _listing_name(code, listing),
                "weight": weight,
                "entry_price": start_px,
                "mark_price": end_px,
                "return": ret,
            }
        )
    return holdings, live, gross


def run_forward_paper(
    *,
    limit: int | None = None,
    start: str | pd.Timestamp | None = None,
    initial_cash: float = INITIAL_CASH_JPY,
) -> dict[str, Any]:
    """確認期間（既定: 2023-01-01）以降の月末リバランスを仮想口座で再生する。"""
    rules = load_adopted()
    limit = limit or rules.universe_limit
    write_liquid_list(limit)
    names = read_liquid_list(limit)
    closes, volumes, bench_raw = _load_bars(names)
    bench = _clean(bench_raw)
    masks = build_masks(closes, bench)
    ready = ready_date(masks)
    if ready is None:
        raise RuntimeError("一次条件を満たす日が無い")
    start_ts = pd.Timestamp(start or TEST_START)
    ready_from = max(ready, start_ts)
    spec = adopted_spec()
    sectors = _sector_map()
    prepared = {code: _clean(series) for code, series in closes.items()}
    try:
        from signalforge.universe.tse_listing import listing_by_ticker

        listing = listing_by_ticker()
    except Exception:
        listing = {}

    months: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    held: dict[str, float] = {}
    equity = 1.0
    bench_eq = 1.0

    for signal, entry, exit_ in monthly_signals(bench, ready):
        if signal < ready_from:
            continue
        holdings, live_weights, gross = _holdings_for(
            spec=spec,
            signal=signal,
            entry=entry,
            mark=exit_,
            masks=masks,
            closes=closes,
            volumes=volumes,
            prepared=prepared,
            sectors=sectors,
            listing=listing,
        )
        nameset = set(held) | set(live_weights)
        one_way = sum(abs(live_weights.get(code, 0.0) - held.get(code, 0.0)) for code in nameset) / 2.0
        cost = one_way * ROUND_TRIP_COST
        bench_entry = _price(bench, entry)
        bench_exit = _price(bench, exit_)
        if bench_entry is None or bench_exit is None:
            continue
        bench_ret = bench_exit / bench_entry - 1.0
        net = gross - cost
        months.append(
            {
                "signal": signal.date().isoformat(),
                "entry": entry.date().isoformat(),
                "exit": exit_.date().isoformat(),
                "n": len(holdings),
                "gross": gross,
                "cost": cost,
                "net": net,
                "bench": bench_ret,
                "excess": net - bench_ret,
                "codes": ",".join(h["code"] for h in holdings),
                "holdings": holdings,
                "open": False,
            }
        )
        equity *= 1.0 + net
        bench_eq *= 1.0 + bench_ret
        equity_curve.append(
            {
                "date": exit_.date().isoformat(),
                "equity": equity,
                "bench_equity": bench_eq,
                "value_jpy": float(initial_cash) * equity,
            }
        )
        held = live_weights

    # 直近の完了月末シグナルがまだクローズ月に無い → マーク・トゥ・マーケット
    latest = latest_signal_day(bench)
    last_closed_signal = pd.Timestamp(months[-1]["signal"]) if months else None
    open_book: dict[str, Any] | None = None
    if last_closed_signal is None or latest > last_closed_signal:
        from signalforge.research.trend_screen.horse import _next_session

        entry = _next_session(bench.index, latest)
        mark = pd.Timestamp(bench.index[-1])
        if entry is not None and mark >= entry:
            holdings, live_weights, gross = _holdings_for(
                spec=spec,
                signal=latest,
                entry=entry,
                mark=mark,
                masks=masks,
                closes=closes,
                volumes=volumes,
                prepared=prepared,
                sectors=sectors,
                listing=listing,
            )
            nameset = set(held) | set(live_weights)
            one_way = sum(abs(live_weights.get(code, 0.0) - held.get(code, 0.0)) for code in nameset) / 2.0
            cost = one_way * ROUND_TRIP_COST
            bench_entry = _price(bench, entry)
            bench_mark = float(bench.iloc[-1])
            if bench_entry is not None:
                bench_ret = bench_mark / bench_entry - 1.0
                net = gross - cost
                open_book = {
                    "signal_date": latest.date().isoformat(),
                    "entry_date": entry.date().isoformat(),
                    "as_of": mark.date().isoformat(),
                    "open": True,
                    "holdings": holdings,
                    "month_net": net,
                    "month_bench": bench_ret,
                    "month_excess": net - bench_ret,
                }
                months.append(
                    {
                        "signal": latest.date().isoformat(),
                        "entry": entry.date().isoformat(),
                        "exit": mark.date().isoformat(),
                        "n": len(holdings),
                        "gross": gross,
                        "cost": cost,
                        "net": net,
                        "bench": bench_ret,
                        "excess": net - bench_ret,
                        "codes": ",".join(h["code"] for h in holdings),
                        "holdings": holdings,
                        "open": True,
                    }
                )

    if open_book is None and months:
        last = months[-1]
        open_book = {
            "signal_date": last["signal"],
            "entry_date": last["entry"],
            "as_of": last["exit"],
            "open": bool(last.get("open")),
            "holdings": last.get("holdings") or [],
            "month_net": last.get("net"),
            "month_bench": last.get("bench"),
            "month_excess": last.get("excess"),
        }

    closed = [row for row in months if not row.get("open")]
    summary = _window_stats(closed)
    # オープン月込みの口座価値（参考）
    live_equity = equity
    live_bench = bench_eq
    if open_book and open_book.get("month_net") is not None:
        live_equity *= 1.0 + float(open_book["month_net"])
        live_bench *= 1.0 + float(open_book["month_bench"] or 0.0)

    return {
        "system_id": rules.id,
        "version": rules.version,
        "name": rules.name,
        "mode": "forward_oos",
        "start": start_ts.date().isoformat(),
        "ready_from": ready_from.date().isoformat(),
        "as_of": pd.Timestamp(bench.index[-1]).date().isoformat(),
        "benchmark": rules.benchmark,
        "initial_cash_jpy": float(initial_cash),
        "n_universe": len(closes),
        "summary": summary,
        "live": {
            "equity": live_equity,
            "bench_equity": live_bench,
            "value_jpy": float(initial_cash) * live_equity,
            "total_return": live_equity - 1.0,
            "bench_total": live_bench - 1.0,
        },
        "open": open_book,
        "months": months,
        "equity_curve": equity_curve,
        "rules_markdown": rules_markdown(rules),
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "note": (
            f"{start_ts.date().isoformat()} 以降の月末判定・翌営業日リバランスを仮想口座で再生。"
            "学習期間は含まない（確認＝フォワード）。未確定の当月は時価評価。"
        ),
    }


def save_forward_paper(payload: dict[str, Any]) -> tuple[Path, Path]:
    paper = paper_path()
    paper.parent.mkdir(parents=True, exist_ok=True)
    paper.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pub = published_forward_path()
    pub.parent.mkdir(parents=True, exist_ok=True)
    slim = {k: v for k, v in payload.items() if k != "months"}
    slim["months"] = [
        {
            "signal": row.get("signal"),
            "entry": row.get("entry"),
            "exit": row.get("exit"),
            "n": row.get("n"),
            "net": row.get("net"),
            "bench": row.get("bench"),
            "excess": row.get("excess"),
            "codes": row.get("codes"),
            "open": row.get("open"),
        }
        for row in (payload.get("months") or [])
    ]
    pub.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    return paper, pub


def run_and_save_forward(*, limit: int | None = None) -> dict[str, Any]:
    payload = run_forward_paper(limit=limit)
    save_forward_paper(payload)
    return payload


def print_forward(payload: dict[str, Any]) -> None:
    s = payload.get("summary") or {}
    live = payload.get("live") or {}
    print(f"{payload.get('name')} v{payload.get('version')} フォワード", flush=True)
    print(
        f"期間 {payload.get('start')} → {payload.get('as_of')}  "
        f"初期 {float(payload.get('initial_cash_jpy') or 0):,.0f} 円",
        flush=True,
    )
    print(
        f"確定月 CAGR {_pct(s.get('cagr'))}  ベンチ {_pct(s.get('bench_cagr'))}  "
        f"累積 {_pct(s.get('total_return'))}  超過累積 {_pct(s.get('excess_total'))}  "
        f"最大DD {_pct(s.get('max_dd'))}",
        flush=True,
    )
    print(
        f"投資月 {s.get('n_invested')}/{s.get('n_months')}  "
        f"平均銘柄 {float(s.get('avg_names') or 0):.1f}  "
        f"超過勝率 {_pct(s.get('hit_rate'))}  月次超過平均 {_pct(s.get('mean_excess'))}",
        flush=True,
    )
    print(
        f"時価込み 口座 {_pct(live.get('total_return'))}  "
        f"({float(live.get('value_jpy') or 0):,.0f} 円)  ベンチ {_pct(live.get('bench_total'))}",
        flush=True,
    )
    open_book = payload.get("open") or {}
    print(
        f"直近 {open_book.get('signal_date')} → {open_book.get('as_of')}  "
        f"月次 {_pct(open_book.get('month_net'))}（超過 {_pct(open_book.get('month_excess'))}）"
        f"{'  [オープン]' if open_book.get('open') else ''}",
        flush=True,
    )
    for h in open_book.get("holdings") or []:
        ret = h.get("return")
        ret_s = "—" if ret is None else f"{ret:+.1%}"
        print(
            f"  - {h.get('code')} {h.get('name')}  {float(h.get('weight') or 0):.0%}  {ret_s}",
            flush=True,
        )
    print(f"口座: {paper_path()}", flush=True)
    print(f"公開: {published_forward_path()}", flush=True)
