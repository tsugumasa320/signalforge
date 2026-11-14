"""一次条件の中で、上昇率上位に絞るか・全部持つかを比べる。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
import pandas as pd

from signalforge.research.trend_screen.config import RET_1Y_STEPS, RET_3Y_STEPS, ROUND_TRIP_COST
from signalforge.research.trend_screen.frequency import (
    _window_freq,
    build_masks,
    monthly_signals,
    ready_date,
)
from signalforge.research.trend_screen.horse import (
    TEST_START,
    TRAIN_END,
    MonthRow,
    VariantResult,
    _clean,
    _pct,
    _price,
    is_confirmed,
)


@dataclass(frozen=True)
class ConcSpec:
    id: str
    title: str
    summary: str
    top_n: int | None  # None = 条件を満たす全銘柄
    rank_by: str  # ret_1y | ret_3y | none


def catalog() -> tuple[ConcSpec, ...]:
    """成績を見る前に固定。判定は月末。一次条件は共通。"""
    base = (
        "一次条件（200日線の上・200日線と75日線が上向き・1年と3年プラス・1年で1306超え）を満たす銘柄。"
    )
    return (
        ConcSpec("all_equal", "全銘柄・等金額", base + " 該当銘柄をすべて等金額。", None, "none"),
        ConcSpec("top5_1y", "1年リターン上位5", base + " 1年株価リターンの高い5銘柄だけ等金額。", 5, "ret_1y"),
        ConcSpec("top3_1y", "1年リターン上位3", base + " 1年株価リターンの高い3銘柄だけ等金額。", 3, "ret_1y"),
        ConcSpec("top1_1y", "1年リターン1位だけ", base + " 1年株価リターンが最も高い1銘柄だけ。", 1, "ret_1y"),
        ConcSpec("top5_3y", "3年リターン上位5", base + " 3年株価リターンの高い5銘柄だけ等金額。", 5, "ret_3y"),
        ConcSpec("top1_3y", "3年リターン1位だけ", base + " 3年株価リターンが最も高い1銘柄だけ。", 1, "ret_3y"),
    )


def _return_at(series: pd.Series, day: pd.Timestamp, steps: int) -> float | None:
    if day not in series.index:
        return None
    loc = series.index.get_loc(day)
    if not isinstance(loc, int) or loc < steps:
        return None
    start = float(series.iloc[loc - steps])
    end = float(series.iloc[loc])
    if start <= 0:
        return None
    return end / start - 1.0


def _pick(
    spec: ConcSpec,
    day: pd.Timestamp,
    masks: dict[str, pd.Series],
    closes: dict[str, pd.Series],
) -> list[str]:
    candidates = [code for code, mask in masks.items() if day in mask.index and bool(mask.loc[day])]
    if not candidates:
        return []
    if spec.top_n is None:
        return sorted(candidates)
    scored: list[tuple[float, str]] = []
    steps = RET_1Y_STEPS if spec.rank_by == "ret_1y" else RET_3Y_STEPS
    for code in candidates:
        value = _return_at(_clean(closes[code]), day, steps)
        if value is None:
            continue
        scored.append((value, code))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [code for _, code in scored[: spec.top_n]]


def _simulate(spec: ConcSpec, masks: dict[str, pd.Series], closes: dict[str, pd.Series], bench: pd.Series, ready: pd.Timestamp) -> VariantResult:
    prepared = {code: _clean(series) for code, series in closes.items()}
    rows: list[MonthRow] = []
    held: dict[str, float] = {}
    for signal, entry, exit_ in monthly_signals(bench, ready):
        chosen = _pick(spec, signal, masks, closes)
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
        rows.append(
            MonthRow(
                variant=spec.id,
                signal=signal.date().isoformat(),
                n=len(tradable),
                gross=gross,
                cost=cost,
                net=gross - cost,
                bench=bench_ret,
                excess=gross - cost - bench_ret,
                codes=",".join(tradable),
            )
        )
        held = weights
    train = [row for row in rows if pd.Timestamp(row.signal) <= TRAIN_END]
    test = [row for row in rows if pd.Timestamp(row.signal) >= TEST_START]
    return VariantResult(
        spec.id,
        spec.title,
        spec.summary,
        _window_freq(train, periods_per_year=12.0),
        _window_freq(test, periods_per_year=12.0),
        rows,
    )


def choose_winner(results: list[VariantResult]) -> VariantResult | None:
    eligible = [
        item
        for item in results
        if item.train.n_invested >= 12 and item.train.cagr is not None and item.train.max_dd is not None
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item.train.cagr, item.train.max_dd), reverse=True)
    return eligible[0]


def run_concentration_race(closes: dict[str, pd.Series], benchmark: pd.Series) -> tuple[list[VariantResult], str | None, bool, str, str]:
    bench = _clean(benchmark)
    print(f"building masks for {len(closes)} names", flush=True)
    masks = build_masks(closes, bench)
    ready = ready_date(masks)
    if ready is None:
        return [], None, False, "一次条件を満たす日が無い。", "未確認"
    results = []
    for spec in catalog():
        print(f"simulate {spec.id}", flush=True)
        results.append(_simulate(spec, masks, closes, bench, ready))
    winner = choose_winner(results)
    confirmed = is_confirmed(winner)
    if winner is None:
        verdict = "学習期間で投資月が足りる案が無く、ベストは選べない。"
    elif confirmed:
        verdict = f"採用は「{winner.title}」。学習期間の口座CAGRが最大で、確認期間でも1306超過がプラスだった。"
    else:
        verdict = f"学習期間の最大は「{winner.title}」。確認期間の超過がプラスでないので、採用は見送り。"
    return results, None if winner is None else winner.id, confirmed, verdict, ready.date().isoformat()


def write_report(
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
    pd.DataFrame([asdict(m) for r in results for m in r.months]).to_csv(
        out / "concentration_months.csv", index=False, encoding="utf-8-sig"
    )
    summary = [
        {
            "id": r.id,
            "title": r.title,
            "train_cagr": r.train.cagr,
            "train_excess": r.train.mean_excess,
            "train_dd": r.train.max_dd,
            "train_invested": r.train.n_invested,
            "train_names": r.train.avg_names,
            "test_cagr": r.test.cagr,
            "test_excess": r.test.mean_excess,
            "test_dd": r.test.max_dd,
            "test_invested": r.test.n_invested,
            "test_names": r.test.avg_names,
        }
        for r in results
    ]
    pd.DataFrame(summary).to_csv(out / "concentration_summary.csv", index=False, encoding="utf-8-sig")
    note = (
        "一次条件と月末判定は共通。変えたのは、該当銘柄を全部持つか、上昇率上位だけ持つか。"
        "上昇率はシグナル日時点の過去1年または3年の株価リターン。"
        "最良は学習期間の口座CAGR。確認は2023年以降の1306超過がプラスかどうかだけ。"
    )
    lines = [
        "# 全銘柄 vs 上昇率上位への集中",
        "",
        f"- 基準日: {as_of}",
        f"- 一次条件開始: {ready_from}",
        f"- 銘柄数: {len(names)}",
        f"- {note}",
        "",
        f"**{verdict}**",
        "",
        "| 案 | 学習CAGR | 学習超過 | 学習DD | 学習平均銘柄 | 確認CAGR | 確認超過 | 確認DD | 確認平均銘柄 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        mark = ""
        if r.id == winner_id:
            mark = " 採用" if confirmed else " 学習最大"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{r.title}{mark}",
                    _pct(r.train.cagr),
                    _pct(r.train.mean_excess),
                    _pct(r.train.max_dd),
                    "未確認" if r.train.avg_names is None else f"{r.train.avg_names:.1f}",
                    _pct(r.test.cagr),
                    _pct(r.test.mean_excess),
                    _pct(r.test.max_dd),
                    "未確認" if r.test.avg_names is None else f"{r.test.avg_names:.1f}",
                ]
            )
            + " |"
        )
    lines.extend(["", "## 定義", ""])
    for r in results:
        lines.append(f"- {r.title}: {r.summary}")
    lines.append("")
    (out / "concentration.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "concentration.json").write_text(
        json.dumps(
            {
                "as_of": as_of,
                "ready_from": ready_from,
                "winner_id": winner_id,
                "confirmed": confirmed,
                "verdict": verdict,
                "note": note,
                "names": names,
                "results": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def run_cached_concentration(*, limit: int = 300) -> Path:
    from signalforge.config import data_dir
    from signalforge.research.trend_screen.horse import _load_bars
    from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

    write_liquid_list(limit)
    closes, _volumes, bench = _load_bars(read_liquid_list(limit))
    results, winner_id, confirmed, verdict, ready = run_concentration_race(closes, bench)
    as_of = _clean(bench).index[-1].date().isoformat()
    out = data_dir() / "reports" / "trend_screen" / "concentration" / as_of
    write_report(
        out=out,
        results=results,
        winner_id=winner_id,
        confirmed=confirmed,
        verdict=verdict,
        names=sorted(closes),
        as_of=as_of,
        ready_from=ready,
    )
    print(verdict, flush=True)
    for r in results:
        flag = " *" if r.id == winner_id else ""
        print(
            f"{r.title}{flag} train {r.train.cagr:+.2%} / {r.train.avg_names:.1f}名 | "
            f"test {r.test.cagr:+.2%} excess {r.test.mean_excess:+.2%}",
            flush=True,
        )
    print(f"出力: {out / 'concentration.md'}", flush=True)
    return out
