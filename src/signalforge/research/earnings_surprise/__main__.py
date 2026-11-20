"""Run the earnings-surprise study.

Examples
--------
uv run python -m signalforge.research.earnings_surprise probe
uv run python -m signalforge.research.earnings_surprise inspect --code 72030
uv run python -m signalforge.research.earnings_surprise fetch-sample --n 100
uv run python -m signalforge.research.earnings_surprise run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from signalforge.research.earnings_surprise.config import REQUESTED_YEARS, RULES_VERSION
from signalforge.research.earnings_surprise.events import build_events
from signalforge.research.earnings_surprise.features import build_candidates
from signalforge.research.earnings_surprise.fetch import DATA, fetch_codes, fetch_sample, load_cache, plan_window
from signalforge.research.earnings_surprise.panel import entry_timing
from signalforge.research.earnings_surprise.report import write_outputs
from signalforge.research.earnings_surprise.simulate import build_books, simulate


def _probe() -> dict:
    start, end = plan_window()
    payload = {
        "rules": RULES_VERSION,
        "requested_years": REQUESTED_YEARS,
        "plan_start": start.isoformat(),
        "plan_end": end.isoformat(),
        "five_year_history": False,
        "prices": "/equities/bars/daily",
        "financials": "/fins/summary",
        "consensus": "このプランの応答にアナリストコンセンサスは無い",
        "official_indices": "TOPIX・日経平均・業種指数は 403",
        "benchmark": "13060（1306 TOPIX連動ETF）の調整後株価",
        "minute_bars": "403。翌営業日VWAPは検証できない",
        "earnings_calendar": "code を指定してもその銘柄の過去発表は返らない。日時は fins/summary の DiscDate と DiscTime",
        "limit_prices": "UL/LL はほぼ 0。ストップ高の判定には使わない",
        "entry": "日足のため、場中発表も翌営業日の寄り付き。当日終値では買わない",
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "probe.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for key, value in payload.items():
        print(f"{key}: {value}")
    return payload


def _inspect(code: str) -> None:
    fetch_codes([code])
    panel, book, fins, _meta = load_cache()
    events = [event for event in build_events(fins) if event.code == code]
    print("code disc_date disc_time period pre_date entry_date entry_open c0 rev_op op_yoy")
    for event in sorted(events, key=lambda item: (item.disc_date, item.disc_time)):
        timing = entry_timing(panel.clock, event.disc_date, event.disc_time)
        opened = None
        if timing is not None:
            series = panel.series.get(code)
            if series is not None and series.at(timing.entry_date) is not None:
                opened = series.raw_o[series.at(timing.entry_date)]
        listing = book.asof(event.disc_date).get(code)
        print(
            code,
            event.disc_date,
            event.disc_time or "-",
            event.period or "-",
            None if timing is None else timing.pre_date,
            None if timing is None else timing.entry_date,
            opened,
            event.c0,
            event.rev_op,
            None if event.op_yoy is None else round(event.op_yoy, 3),
            None if listing is None else listing.sector,
            "consensus",
            event.consensus_op,
        )


def _run(out: Path) -> None:
    panel, book, fins, meta = load_cache()
    events = build_events(fins)
    candidates, counts = build_candidates(events, panel, book)
    trades, exclusions = simulate(candidates, panel)
    books = build_books(trades, panel)
    anomalies = panel.anomaly_counts()
    names = meta.get("names")
    meta.update(anomalies)
    meta["names"] = names
    meta["price_files"] = anomalies["names"]
    meta["requested_years"] = REQUESTED_YEARS
    meta["consensus"] = "未取得。C0は会社予想の上方修正、または増益かつ利益率改善。"
    meta["minute_bars"] = "未取得。方法Bは未実施。"
    meta["limit_prices"] = "UL/LLはほぼ空のため未使用。"
    names = int(meta.get("names") or 0)
    if names < 500:
        meta["sector_note"] = "キャッシュにある銘柄だけの等ウェイト。プライム全体の業種指数ではない。"
        meta["mode"] = meta.get("mode") or "sample"
    else:
        meta["sector_note"] = "キャッシュ内のプライム普通株の等ウェイト。公式の業種指数ではない。"
    path = write_outputs(out, trades, exclusions, books, meta, counts)
    print(f"events={counts.get('events')} c0={counts.get('c0')} c3={counts.get('c3')} trades={len(trades)}")
    print(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="決算サプライズ C0–C3")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--code", default="72030")
    sample = sub.add_parser("fetch-sample")
    sample.add_argument("--n", type=int, default=100)
    run = sub.add_parser("run")
    run.add_argument("--out", type=Path, default=DATA / "output")
    args = parser.parse_args()
    if args.cmd == "probe":
        _probe()
    elif args.cmd == "inspect":
        _inspect(args.code)
    elif args.cmd == "fetch-sample":
        note = fetch_sample(args.n)
        print(json.dumps(note, ensure_ascii=False))
    elif args.cmd == "run":
        _run(args.out)


if __name__ == "__main__":
    main()
