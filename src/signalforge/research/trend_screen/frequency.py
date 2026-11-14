"""同じ一次条件で、月末判定と毎日判定を比べる。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from signalforge.research.trend_screen.config import (
    MA200_SLOPE_LAG,
    MA75_SLOPE_LAG,
    RET_1Y_STEPS,
    RET_3Y_STEPS,
    ROUND_TRIP_COST,
)
from signalforge.research.trend_screen.horse import (
    TEST_START,
    TRAIN_END,
    WindowStats,
    _clean,
    _month_ends,
    _next_session,
    _pct,
    _price,
    is_confirmed,
    MonthRow,
    VariantResult,
)

MIN_DAILY_INVESTED = 252


@dataclass(frozen=True)
class FreqSpec:
    id: str
    title: str
    summary: str
    frequency: str  # monthly | daily
    min_invested: int


def specs() -> tuple[FreqSpec, ...]:
    """成績を見る前に固定。一次条件は同じで、判定頻度だけ変える。"""
    rule = (
        "終値が200日線より上、200日線が60営業日前より上、75日線が20営業日前より上、"
        "1年と3年の株価リターンがプラス、1年で1306を上回る。"
    )
    return (
        FreqSpec(
            "primary_monthly",
            "一次条件・月末判定",
            rule + " 毎月末に判定し、翌営業日から次の月末の翌営業日まで等金額で持つ。",
            "monthly",
            12,
        ),
        FreqSpec(
            "primary_daily",
            "一次条件・毎日判定",
            rule + " 毎日の終値で判定し、翌営業日から翌々営業日まで等金額で持つ。",
            "daily",
            MIN_DAILY_INVESTED,
        ),
    )


def primary_mask(close: pd.Series, benchmark: pd.Series) -> pd.Series:
    px = _clean(close)
    bench = _clean(benchmark).reindex(px.index)
    # ベンチが欠損の日は相対条件を付けない（False）
    ma75 = px.rolling(75, min_periods=75).mean()
    ma200 = px.rolling(200, min_periods=200).mean()
    stock_1 = px / px.shift(RET_1Y_STEPS) - 1.0
    stock_3 = px / px.shift(RET_3Y_STEPS) - 1.0
    bench_1 = bench / bench.shift(RET_1Y_STEPS) - 1.0
    mask = (
        (px > ma200)
        & (ma200 > ma200.shift(MA200_SLOPE_LAG))
        & (ma75 > ma75.shift(MA75_SLOPE_LAG))
        & (stock_1 > 0)
        & (stock_3 > 0)
        & (bench_1.notna())
        & ((stock_1 - bench_1) > 0)
    )
    return mask.fillna(False)


def build_masks(closes: dict[str, pd.Series], benchmark: pd.Series) -> dict[str, pd.Series]:
    bench = _clean(benchmark)
    out: dict[str, pd.Series] = {}
    for i, (code, series) in enumerate(closes.items(), start=1):
        out[code] = primary_mask(series, bench)
        if i % 50 == 0 or i == len(closes):
            print(f"masks {i}/{len(closes)}", flush=True)
    return out


def _chosen(masks: dict[str, pd.Series], day: pd.Timestamp) -> list[str]:
    found: list[str] = []
    for code, mask in masks.items():
        if day in mask.index and bool(mask.loc[day]):
            found.append(code)
    return sorted(found)


def _window_freq(rows: list[MonthRow], *, periods_per_year: float) -> WindowStats:
    stats = WindowStats(n_months=len(rows))
    if not rows:
        return stats
    stats.start = rows[0].signal
    stats.end = rows[-1].signal
    stats.n_invested = sum(1 for row in rows if row.n > 0)
    stats.mean_excess = sum(row.excess for row in rows) / len(rows)
    stats.mean_return = sum(row.net for row in rows) / len(rows)
    stats.hit_rate = sum(1 for row in rows if row.excess > 0) / len(rows)
    stats.avg_names = sum(row.n for row in rows) / len(rows)
    equity = 1.0
    bench_equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for row in rows:
        equity *= 1.0 + row.net
        bench_equity *= 1.0 + row.bench
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0)
    stats.total_return = equity - 1.0
    stats.bench_total = bench_equity - 1.0
    stats.max_dd = max_dd
    if len(rows) > 0 and equity > 0:
        stats.cagr = equity ** (periods_per_year / len(rows)) - 1.0
        stats.bench_cagr = bench_equity ** (periods_per_year / len(rows)) - 1.0
    return stats


def _simulate_span(
    *,
    spec: FreqSpec,
    signals: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]],
    masks: dict[str, pd.Series],
    closes: dict[str, pd.Series],
    bench: pd.Series,
) -> VariantResult:
    prepared = {code: _clean(series) for code, series in closes.items()}
    rows: list[MonthRow] = []
    held: dict[str, float] = {}
    for signal, entry, exit_ in signals:
        chosen = _chosen(masks, signal)
        rets: list[float] = []
        tradable: list[str] = []
        for code in chosen:
            series = prepared.get(code)
            if series is None:
                continue
            start_px = _price(series, entry)
            end_px = _price(series, exit_)
            if start_px is None or end_px is None:
                continue
            tradable.append(code)
            rets.append(end_px / start_px - 1.0)
        weights = {code: 1.0 / len(tradable) for code in tradable}
        names = set(held) | set(weights)
        one_way = sum(abs(weights.get(code, 0.0) - held.get(code, 0.0)) for code in names) / 2.0
        cost = one_way * ROUND_TRIP_COST
        gross = sum(rets) / len(rets) if rets else 0.0
        bench_entry = _price(bench, entry)
        bench_exit = _price(bench, exit_)
        if bench_entry is None or bench_exit is None:
            continue
        bench_ret = bench_exit / bench_entry - 1.0
        net = gross - cost
        rows.append(
            MonthRow(
                variant=spec.id,
                signal=signal.date().isoformat(),
                n=len(tradable),
                gross=gross,
                cost=cost,
                net=net,
                bench=bench_ret,
                excess=net - bench_ret,
                codes=",".join(tradable),
            )
        )
        held = weights
    train_rows = [row for row in rows if pd.Timestamp(row.signal) <= TRAIN_END]
    test_rows = [row for row in rows if pd.Timestamp(row.signal) >= TEST_START]
    periods = 12.0 if spec.frequency == "monthly" else 245.0
    return VariantResult(
        spec.id,
        spec.title,
        spec.summary,
        _window_freq(train_rows, periods_per_year=periods),
        _window_freq(test_rows, periods_per_year=periods),
        rows,
    )


def monthly_signals(bench: pd.Series, ready_from: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    ends = [day for day in _month_ends(bench.index) if day >= ready_from]
    out: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    for left, right in zip(ends, ends[1:]):
        entry = _next_session(bench.index, left)
        exit_ = _next_session(bench.index, right)
        if entry is None or exit_ is None:
            continue
        out.append((pd.Timestamp(left), entry, exit_))
    return out


def daily_signals(bench: pd.Series, ready_from: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    sessions = list(bench.index)
    out: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    for i in range(len(sessions) - 2):
        signal = pd.Timestamp(sessions[i])
        if signal < ready_from:
            continue
        entry = pd.Timestamp(sessions[i + 1])
        exit_ = pd.Timestamp(sessions[i + 2])
        out.append((signal, entry, exit_))
    return out


def ready_date(masks: dict[str, pd.Series]) -> pd.Timestamp | None:
    first: pd.Timestamp | None = None
    for mask in masks.values():
        hits = mask[mask].index
        if len(hits) == 0:
            continue
        day = pd.Timestamp(hits[0])
        if first is None or day < first:
            first = day
    return first


def choose_freq_winner(results: list[VariantResult], specs_by_id: dict[str, FreqSpec]) -> VariantResult | None:
    eligible = []
    for item in results:
        need = specs_by_id[item.id].min_invested
        if item.train.n_invested >= need and item.train.cagr is not None and item.train.max_dd is not None:
            eligible.append(item)
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item.train.cagr, item.train.max_dd), reverse=True)
    return eligible[0]


def run_frequency_race(
    closes: dict[str, pd.Series],
    benchmark: pd.Series,
) -> tuple[list[VariantResult], str | None, bool, str, str]:
    bench = _clean(benchmark)
    print(f"building primary masks for {len(closes)} names", flush=True)
    masks = build_masks(closes, bench)
    ready = ready_date(masks)
    if ready is None:
        return [], None, False, "一次条件を満たす日が無く、比較できない。", "未確認"
    ready_text = ready.date().isoformat()
    print(f"ready_from {ready_text}", flush=True)
    results: list[VariantResult] = []
    catalog = specs()
    by_id = {item.id: item for item in catalog}
    for spec in catalog:
        print(f"simulate {spec.id}", flush=True)
        if spec.frequency == "monthly":
            signals = monthly_signals(bench, ready)
        else:
            signals = daily_signals(bench, ready)
        results.append(_simulate_span(spec=spec, signals=signals, masks=masks, closes=closes, bench=bench))
    winner = choose_freq_winner(results, by_id)
    confirmed = is_confirmed(winner)
    if winner is None:
        verdict = "学習期間の投資日数が足りる案が無く、ベストは選べない。"
    elif confirmed:
        verdict = (
            f"採用は「{winner.title}」。"
            "学習期間の口座CAGRが最大で、確認期間でも1306への超過がプラスだった。"
        )
    else:
        verdict = (
            f"学習期間の最大は「{winner.title}」。"
            "確認期間では1306への超過がプラスにならなかったので、採用は見送り。"
        )
    return results, None if winner is None else winner.id, confirmed, verdict, ready_text


def write_frequency_report(
    *,
    out: Path,
    results: list[VariantResult],
    winner_id: str | None,
    confirmed: bool,
    verdict: str,
    names: list[str],
    as_of: str,
    ready_from: str,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rows = [asdict(month) for result in results for month in result.months]
    pd.DataFrame(rows).to_csv(out / "frequency_monthly.csv", index=False, encoding="utf-8-sig")
    summary = []
    for result in results:
        summary.append(
            {
                "id": result.id,
                "title": result.title,
                "train_cagr": result.train.cagr,
                "train_excess": result.train.mean_excess,
                "train_dd": result.train.max_dd,
                "train_invested": result.train.n_invested,
                "train_names": result.train.avg_names,
                "train_mean_cost": None
                if not result.months
                else sum(m.cost for m in result.months if pd.Timestamp(m.signal) <= TRAIN_END)
                / max(1, sum(1 for m in result.months if pd.Timestamp(m.signal) <= TRAIN_END)),
                "test_cagr": result.test.cagr,
                "test_excess": result.test.mean_excess,
                "test_dd": result.test.max_dd,
                "test_invested": result.test.n_invested,
                "test_names": result.test.avg_names,
            }
        )
    pd.DataFrame(summary).to_csv(out / "frequency_summary.csv", index=False, encoding="utf-8-sig")
    note = (
        "一次条件は同じ。変えたのは判定頻度だけ。"
        "月末判定は翌営業日から次の月末の翌営業日まで保有。"
        "毎日判定は翌営業日から翌々営業日まで保有し、毎日入れ替えコスト（往復0.2%×売買割合）を取る。"
        "最良は学習期間（〜2022-12-31）の口座CAGR。月末案は投資月12以上、毎日案は投資日252以上。"
        "確認は2023-01-01以降の超過がプラスかどうかだけ。選び直しには使わない。"
        "母集団は現存の流動性上位で、生存者バイアスがある。"
    )
    payload = {
        "as_of": as_of,
        "ready_from": ready_from,
        "names": names,
        "winner_id": winner_id,
        "confirmed": confirmed,
        "verdict": verdict,
        "note": note,
        "results": [
            {"id": r.id, "title": r.title, "summary": r.summary, "train": asdict(r.train), "test": asdict(r.test)}
            for r in results
        ],
    }
    (out / "frequency.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 月末判定 vs 毎日判定",
        "",
        f"- 基準日: {as_of}",
        f"- 一次条件が初めて揃った日: {ready_from}",
        f"- 銘柄数: {len(names)}",
        f"- {note}",
        "",
        f"**{verdict}**",
        "",
        "| 案 | 学習CAGR | 学習超過 | 学習DD | 学習の投資回数 | 学習平均銘柄 | 確認CAGR | 確認超過 | 確認DD | 確認の投資回数 | 確認平均銘柄 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        mark = ""
        if result.id == winner_id:
            mark = " 採用" if confirmed else " 学習最大"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{result.title}{mark}",
                    _pct(result.train.cagr),
                    _pct(result.train.mean_excess),
                    _pct(result.train.max_dd),
                    str(result.train.n_invested),
                    "未確認" if result.train.avg_names is None else f"{result.train.avg_names:.1f}",
                    _pct(result.test.cagr),
                    _pct(result.test.mean_excess),
                    _pct(result.test.max_dd),
                    str(result.test.n_invested),
                    "未確認" if result.test.avg_names is None else f"{result.test.avg_names:.1f}",
                ]
            )
            + " |"
        )
    lines.extend(["", "## 定義", ""])
    for result in results:
        lines.append(f"- {result.title}: {result.summary}")
    lines.append("")
    (out / "frequency.md").write_text("\n".join(lines), encoding="utf-8")


def run_cached_frequency(*, limit: int = 300) -> Path:
    from signalforge.config import data_dir
    from signalforge.research.trend_screen.horse import _load_bars
    from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

    write_liquid_list(limit)
    names = read_liquid_list(limit)
    closes, _volumes, bench = _load_bars(names)
    results, winner_id, confirmed, verdict, ready_from = run_frequency_race(closes, bench)
    as_of = _clean(bench).index[-1].date().isoformat()
    out = data_dir() / "reports" / "trend_screen" / "frequency" / as_of
    write_frequency_report(
        out=out,
        results=results,
        winner_id=winner_id,
        confirmed=confirmed,
        verdict=verdict,
        names=sorted(closes),
        as_of=as_of,
        ready_from=ready_from,
    )
    print(verdict, flush=True)
    for result in results:
        flag = " *" if result.id == winner_id else ""
        print(
            f"{result.title}{flag} train CAGR {result.train.cagr:+.2%} excess {result.train.mean_excess:+.2%} "
            f"| test CAGR {result.test.cagr:+.2%} excess {result.test.mean_excess:+.2%} "
            f"| invested train {result.train.n_invested} test {result.test.n_invested}",
            flush=True,
        )
    print(f"出力: {out / 'frequency.md'}", flush=True)
    return out
