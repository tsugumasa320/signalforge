"""採用ルールのシストレ実行：現状の目標ポートフォリオと月末リバランス用バックテスト。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from signalforge.config import data_dir
from signalforge.research.trend_screen.frequency import build_masks, ready_date
from signalforge.research.trend_screen.horse import _clean, _load_bars, _month_ends, _pct
from signalforge.research.trend_screen.improve import ImproveSpec, _sector_map, _simulate as improve_simulate, _stats_at, select_names, _weights
from signalforge.research.trend_screen.ruleset import load_adopted, rules_markdown
from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list


def adopted_spec() -> ImproveSpec:
    rules = load_adopted()
    return ImproveSpec(
        id=rules.id,
        title=rules.name,
        summary="採用シストレ（ruleset / adopted.json）",
        top_n=rules.top_n,
        rank_by=rules.rank_by,
        weight=rules.weight,
        sector_max=rules.sector_max,
        min_turnover=rules.min_turnover,
        min_ret_20d=rules.min_ret_20d,
        require_above_ma25=rules.require_above_ma25,
        max_dd_52w=rules.max_dd_52w,
    )


@dataclass
class TargetBook:
    system_id: str
    version: str
    signal_date: str
    entry_date: str | None
    benchmark: str
    n_universe: int
    n_primary: int
    n_on_signal: int = 0
    coverage_ok: bool = True
    warning: str = ""
    targets: list[dict] = field(default_factory=list)
    generated_at: str = ""


def state_path() -> Path:
    rules = load_adopted()
    return data_dir() / "trend_screen" / "system" / f"{rules.id}.json"


def save_targets(book: TargetBook) -> Path:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(book), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_targets() -> TargetBook | None:
    path = state_path()
    if not path.exists():
        return None
    return TargetBook(**json.loads(path.read_text(encoding="utf-8")))


def _next_session(index: pd.DatetimeIndex, day: pd.Timestamp) -> pd.Timestamp | None:
    pos = int(index.searchsorted(pd.Timestamp(day), side="right"))
    if pos >= len(index):
        return None
    return pd.Timestamp(index[pos])


def _is_month_end_session(day: pd.Timestamp) -> bool:
    """翌営業日のカレンダー月が変われば、その日は月末セッション。"""
    from pandas.tseries.offsets import BDay

    day = pd.Timestamp(day).normalize()
    nxt = day + BDay(1)
    return int(nxt.month) != int(day.month)


def latest_signal_day(bench: pd.Series) -> pd.Timestamp:
    """直近の『完了した月』の月末。月中の最終バーを月末扱いしない。"""
    index = _clean(bench).index
    ends = _month_ends(index)
    if not ends:
        raise RuntimeError("ベンチマークの月末が取れない")
    last = pd.Timestamp(index[-1]).normalize()
    months = sorted({(pd.Timestamp(day).year, pd.Timestamp(day).month) for day in index})
    completed = set(months[:-1])
    if _is_month_end_session(last):
        completed.add((last.year, last.month))
    closed = [day for day in ends if (day.year, day.month) in completed]
    if not closed:
        raise RuntimeError("完了した月末シグナルがまだない")
    return closed[-1]


def _signal_coverage(closes: dict[str, pd.Series], signal: pd.Timestamp) -> tuple[int, bool, str]:
    """シグナル日に終値がある銘柄数。ユニバースの9割未満なら警告。"""
    n_on = sum(1 for series in closes.values() if signal in _clean(series).index)
    n_uni = len(closes)
    if n_uni <= 0:
        return 0, False, "ユニバースが空"
    ratio = n_on / n_uni
    if ratio < 0.9:
        return (
            n_on,
            False,
            f"シグナル日 {signal.date().isoformat()} の日足が {n_on}/{n_uni} しかない。"
            " `uv run signalforge fetch --update` で流動性ユニバースを更新してから再実行。",
        )
    return n_on, True, ""


def compute_targets(*, limit: int | None = None) -> TargetBook:
    rules = load_adopted()
    limit = limit or rules.universe_limit
    write_liquid_list(limit)
    names = read_liquid_list(limit)
    closes, volumes, bench = _load_bars(names)
    bench = _clean(bench)
    masks = build_masks(closes, bench)
    signal = latest_signal_day(bench)
    n_on_signal, coverage_ok, warning = _signal_coverage(closes, signal)
    primary = [code for code, mask in masks.items() if signal in mask.index and bool(mask.loc[signal])]
    spec = adopted_spec()
    sectors = _sector_map()
    chosen = select_names(spec, signal, masks, closes, volumes, sectors)
    weights = _weights(spec, chosen, signal, closes, volumes)
    entry = _next_session(bench.index, signal)
    from signalforge.universe.tse_listing import listing_by_ticker

    listing = listing_by_ticker()
    targets = []
    for code in chosen:
        stats = _stats_at(closes[code], volumes.get(code), signal)
        price = None
        clean = _clean(closes[code])
        if signal in clean.index:
            price = float(clean.loc[signal])
        sym = code.replace(".T", "")
        meta = listing.get(code) or listing.get(sym) or {}
        targets.append(
            {
                "ticker": code,
                "name": str(meta.get("name") or ""),
                "weight": weights.get(code, 0.0),
                "price_on_signal": price,
                "ret_1y": stats["ret_1y"],
                "vol_1y": stats["vol_1y"],
            }
        )
    book = TargetBook(
        system_id=rules.id,
        version=rules.version,
        signal_date=signal.date().isoformat(),
        entry_date=None if entry is None else entry.date().isoformat(),
        benchmark=rules.benchmark,
        n_universe=len(closes),
        n_primary=len(primary),
        n_on_signal=n_on_signal,
        coverage_ok=coverage_ok,
        warning=warning,
        targets=targets,
        generated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    )
    save_targets(book)
    return book


def run_system_backtest(*, limit: int | None = None) -> dict:
    rules = load_adopted()
    limit = limit or rules.universe_limit
    write_liquid_list(limit)
    closes, volumes, bench = _load_bars(read_liquid_list(limit))
    bench = _clean(bench)
    masks = build_masks(closes, bench)
    ready = ready_date(masks)
    if ready is None:
        raise RuntimeError("一次条件を満たす日が無い")
    result = improve_simulate(adopted_spec(), masks, closes, volumes, bench, ready, _sector_map())
    out = data_dir() / "reports" / "trend_screen" / "system" / bench.index[-1].date().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    months = pd.DataFrame([asdict(m) for m in result.months])
    months.to_csv(out / "months.csv", index=False, encoding="utf-8-sig")
    summary = {
        "system_id": rules.id,
        "version": rules.version,
        "ready_from": ready.date().isoformat(),
        "as_of": bench.index[-1].date().isoformat(),
        "n_names": len(closes),
        "train": asdict(result.train),
        "test": asdict(result.test),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "rules.md").write_text(rules_markdown(rules), encoding="utf-8")
    lines = [
        f"# {rules.name} バックテスト",
        "",
        f"- 版: {rules.version}",
        f"- ユニバース: {len(closes)}",
        f"- 開始可能: {ready.date().isoformat()}",
        f"- 基準日: {bench.index[-1].date().isoformat()}",
        "",
        "| 期間 | CAGR | 月次超過 | 最大DD | 投資月 | 平均銘柄 |",
        "| --- | --- | --- | --- | --- | --- |",
        "| 学習〜2022 | "
        + " | ".join(
            [
                _pct(result.train.cagr),
                _pct(result.train.mean_excess),
                _pct(result.train.max_dd),
                str(result.train.n_invested),
                f"{result.train.avg_names:.1f}" if result.train.avg_names is not None else "未確認",
            ]
        )
        + " |",
        "| 確認2023〜 | "
        + " | ".join(
            [
                _pct(result.test.cagr),
                _pct(result.test.mean_excess),
                _pct(result.test.max_dd),
                str(result.test.n_invested),
                f"{result.test.avg_names:.1f}" if result.test.avg_names is not None else "未確認",
            ]
        )
        + " |",
        "",
    ]
    (out / "backtest.md").write_text("\n".join(lines), encoding="utf-8")
    return {"out": out, "train": result.train, "test": result.test, "summary": summary}


def print_targets(book: TargetBook) -> None:
    rules = load_adopted()
    print(f"{rules.name} v{book.version}", flush=True)
    print(
        f"シグナル {book.signal_date} → エントリー予定 {book.entry_date or '未確定'} "
        f"（ユニバース {book.n_universe} / シグナル日バー {book.n_on_signal} / "
        f"一次条件 {book.n_primary} / 保有 {len(book.targets)}）",
        flush=True,
    )
    if book.warning:
        print(f"警告: {book.warning}", flush=True)
    if not book.targets:
        print("今月の目標銘柄はない。", flush=True)
        return
    for i, row in enumerate(book.targets, start=1):
        ret = "未確認" if row.get("ret_1y") is None else f"{row['ret_1y']:+.1%}"
        px = "未確認" if row.get("price_on_signal") is None else f"{row['price_on_signal']:,.0f}"
        name = str(row.get("name") or "").strip() or "（社名未取得）"
        print(
            f"{i}. {row['ticker'].replace('.T', '')} {name}  weight {row['weight']:.0%}  "
            f"1年 {ret}  終値 {px}",
            flush=True,
        )


def print_rules() -> None:
    print(rules_markdown(), flush=True)
