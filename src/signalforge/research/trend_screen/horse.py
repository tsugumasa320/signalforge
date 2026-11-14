"""選別案を月次の等金額で比べる。学習期間の口座CAGRだけで最良を決める。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from signalforge.research.trend_screen.chart import ChartMetrics, evaluate_chart
from signalforge.research.trend_screen.config import ROUND_TRIP_COST
from signalforge.research.trend_screen.fund_asof import growth_ok
from signalforge.research.trend_screen.fundamentals import AnnualPoint
from signalforge.research.trend_screen.variants import Variant, catalog, passes_entry

TRAIN_END = pd.Timestamp("2022-12-31")
TEST_START = pd.Timestamp("2023-01-01")
MIN_MONTHS = 12
BENCHMARK = "1306.T"


@dataclass
class WindowStats:
    start: str | None = None
    end: str | None = None
    n_months: int = 0
    n_invested: int = 0
    mean_excess: float | None = None
    mean_return: float | None = None
    hit_rate: float | None = None
    total_return: float | None = None
    bench_total: float | None = None
    max_dd: float | None = None
    avg_names: float | None = None
    cagr: float | None = None
    bench_cagr: float | None = None


@dataclass
class MonthRow:
    variant: str
    signal: str
    n: int
    gross: float
    cost: float
    net: float
    bench: float
    excess: float
    codes: str
    regime: str = ""


@dataclass
class VariantResult:
    id: str
    title: str
    summary: str
    train: WindowStats
    test: WindowStats
    months: list[MonthRow] = field(default_factory=list)


@dataclass
class Race:
    as_of: str
    names: list[str]
    ready_from: str | None
    results: list[VariantResult]
    winner_id: str | None
    confirmed: bool
    verdict: str
    note: str
    fund_coverage: str = ""


def _clean(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    index = pd.DatetimeIndex(pd.to_datetime(out.index))
    if index.tz is not None:
        index = index.tz_localize(None)
    out.index = index.normalize()
    out = out.dropna()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def _month_ends(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    last: dict[tuple[int, int], pd.Timestamp] = {}
    for stamp in index:
        last[(int(stamp.year), int(stamp.month))] = pd.Timestamp(stamp)
    return [last[key] for key in sorted(last)]


def _next_session(index: pd.DatetimeIndex, day: pd.Timestamp) -> pd.Timestamp | None:
    pos = int(index.searchsorted(pd.Timestamp(day), side="right"))
    if pos >= len(index):
        return None
    return pd.Timestamp(index[pos])


def regime_flags(benchmark: pd.Series, day: pd.Timestamp) -> dict[str, bool | None]:
    hist = benchmark.loc[: pd.Timestamp(day)]
    if len(hist) < 200:
        return {"above200": None, "uptrend": None}
    average = hist.rolling(200, min_periods=200).mean()
    ma_now = float(average.iloc[-1])
    price = float(hist.iloc[-1])
    if ma_now <= 0:
        return {"above200": None, "uptrend": None}
    above = price > ma_now
    if len(average.dropna()) <= 60 or float(average.iloc[-61]) <= 0:
        rising: bool | None = None
    else:
        rising = ma_now > float(average.iloc[-61])
    return {"above200": above, "uptrend": above and rising is True}


def _price(series: pd.Series, day: pd.Timestamp) -> float | None:
    try:
        value = float(series.loc[day])
    except KeyError:
        return None
    if pd.isna(value) or value <= 0:
        return None
    return value


def build_snapshots(
    closes: dict[str, pd.Series],
    volumes: dict[str, pd.Series],
    benchmark: pd.Series,
) -> tuple[list[tuple[pd.Timestamp, dict[str, ChartMetrics]]], pd.Series]:
    bench = _clean(benchmark)
    prepared = {code: _clean(series) for code, series in closes.items()}
    vols = {code: _clean(volumes[code]) for code in prepared if code in volumes}
    snaps: list[tuple[pd.Timestamp, dict[str, ChartMetrics]]] = []
    days = _month_ends(bench.index)
    for i, day in enumerate(days):
        book: dict[str, ChartMetrics] = {}
        for code, series in prepared.items():
            if day not in series.index:
                continue
            hist = series.loc[:day]
            vol = vols.get(code)
            book[code] = evaluate_chart(hist, None if vol is None else vol.reindex(hist.index), None, bench.loc[:day])
        snaps.append((day, book))
        if (i + 1) % 12 == 0:
            print(f"snapshots {i + 1}/{len(days)}", flush=True)
    return snaps, bench


def _window(rows: list[MonthRow]) -> WindowStats:
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
        stats.cagr = equity ** (12.0 / len(rows)) - 1.0
        stats.bench_cagr = bench_equity ** (12.0 / len(rows)) - 1.0
    return stats


def _pick(
    variant: Variant,
    book: dict[str, ChartMetrics],
    fund_map: dict[str, list[AnnualPoint]],
    day: pd.Timestamp,
) -> list[str]:
    chosen = variant.select(book)
    as_of = day.date()
    out: list[str] = []
    for code in chosen:
        metrics = book.get(code)
        if metrics is None or not passes_entry(metrics, variant.entry):
            continue
        if variant.require_fund:
            annuals = fund_map.get(code) or []
            if growth_ok(annuals, as_of) is not True:
                continue
        out.append(code)
    return out


def _simulate(
    variant: Variant,
    snaps: list[tuple[pd.Timestamp, dict[str, ChartMetrics]]],
    closes: dict[str, pd.Series],
    bench: pd.Series,
    ready_from: pd.Timestamp,
    fund_map: dict[str, list[AnnualPoint]],
) -> VariantResult:
    prepared = {code: _clean(series) for code, series in closes.items()}
    ends = [day for day, _ in snaps]
    by_day = {day: book for day, book in snaps}
    rows: list[MonthRow] = []
    held: dict[str, float] = {}
    for left, right in zip(ends, ends[1:]):
        if left < ready_from:
            continue
        entry = _next_session(bench.index, left)
        exit_ = _next_session(bench.index, right)
        if entry is None or exit_ is None:
            continue
        bench_entry = _price(bench, entry)
        bench_exit = _price(bench, exit_)
        if bench_entry is None or bench_exit is None:
            continue
        flags = regime_flags(bench, left)
        if flags.get("uptrend") is True:
            state = "uptrend"
        elif flags.get("above200") is True:
            state = "above200"
        elif flags.get("above200") is False:
            state = "below200"
        else:
            state = "unknown"
        allowed = True if variant.regime is None else flags.get(variant.regime) is True
        chosen = _pick(variant, by_day[left], fund_map, left) if allowed else []
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
        bench_ret = bench_exit / bench_entry - 1.0
        net = gross - cost
        rows.append(
            MonthRow(
                variant=variant.id,
                signal=left.date().isoformat(),
                n=len(tradable),
                gross=gross,
                cost=cost,
                net=net,
                bench=bench_ret,
                excess=net - bench_ret,
                codes=",".join(tradable),
                regime=state,
            )
        )
        held = weights
    train_rows = [row for row in rows if pd.Timestamp(row.signal) <= TRAIN_END]
    test_rows = [row for row in rows if pd.Timestamp(row.signal) >= TEST_START]
    return VariantResult(
        variant.id,
        variant.title,
        variant.summary,
        _window(train_rows),
        _window(test_rows),
        rows,
    )


def choose_winner(results: list[VariantResult]) -> VariantResult | None:
    """学習期間の口座CAGRだけで選ぶ。確認期間の数字は見ない。"""
    eligible = [
        item
        for item in results
        if item.train.n_invested >= MIN_MONTHS and item.train.cagr is not None and item.train.max_dd is not None
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item.train.cagr, item.train.max_dd), reverse=True)
    return eligible[0]


def is_confirmed(winner: VariantResult | None) -> bool:
    if winner is None or winner.test.mean_excess is None or winner.test.cagr is None:
        return False
    return winner.test.n_invested >= MIN_MONTHS and winner.test.mean_excess > 0


def verdict_text(winner: VariantResult | None, confirmed: bool) -> str:
    if winner is None:
        return "学習期間で投資月が12ヶ月に届く案が無く、ベストは選べない。"
    if confirmed:
        return (
            f"採用案は「{winner.title}」。"
            "学習期間の口座CAGRが最大で、確認期間でも1306への月次超過がプラスだった。"
        )
    return (
        f"学習期間の最大は「{winner.title}」。"
        "確認期間では1306への月次超過がプラスにならなかったので、採用は見送り。"
    )


def run_race(
    closes: dict[str, pd.Series],
    volumes: dict[str, pd.Series],
    benchmark: pd.Series,
    *,
    names: list[str] | None = None,
    fund_map: dict[str, list[AnnualPoint]] | None = None,
) -> Race:
    funds = fund_map or {}
    with_fund = sum(1 for code in (names or closes) if growth_ok(funds.get(code) or [], date(2022, 12, 31)) is not None)
    print(f"building monthly snapshots for {len(closes)} names", flush=True)
    snaps, bench = build_snapshots(closes, volumes, benchmark)
    ready = next((day for day, book in snaps if any(item.ret_3y is not None for item in book.values())), None)
    results = []
    if ready is not None:
        for variant in catalog():
            print(f"simulate {variant.id}", flush=True)
            results.append(_simulate(variant, snaps, closes, bench, ready, funds))
    winner = choose_winner(results)
    confirmed = is_confirmed(winner)
    note = (
        "月末の終値で判定し、翌営業日の終値から次の月末の翌営業日まで等金額で持つ。"
        "同じ銘柄を持ち続ける月は売買コストを取らない。入れ替えは往復0.2%を売買した割合だけ負担する。"
        "現金の月はリターン0。"
        "最良案はシグナル日が2022-12-31以前の口座CAGRだけで決める。投資月が12未満は失格。"
        "同点なら学習期間の最大ドローダウンが浅い方。"
        "確認は2023-01-01以降で、1306への月次超過がプラスかどうかだけを見る。選び直しには使わない。"
        "地合い・押し目・業績の条件は成績を見る前に固定した。"
        "業績は通期の期末から90日後以降に使えるとみなした近似で、遡及修正の先読みは残る。"
        "母集団は現存の流動性上位銘柄で、生存者バイアスがある。全市場の検証ではない。"
    )
    return Race(
        as_of=bench.index[-1].date().isoformat() if len(bench) else "",
        names=names if names is not None else sorted(closes),
        ready_from=None if ready is None else ready.date().isoformat(),
        results=results,
        winner_id=None if winner is None else winner.id,
        confirmed=confirmed,
        verdict=verdict_text(winner, confirmed),
        note=note,
        fund_coverage=(
            f"2022-12-31時点で業績3期が揃う銘柄は{with_fund}/{len(names or closes)}。"
            "yfinanceの通期は直近5期程度のため、学習期間では業績案はほぼ測れない。"
        ),
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "未確認"
    return f"{value:+.2%}"


def write_race(race: Race, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for result in race.results:
        for month in result.months:
            rows.append(asdict(month))
    pd.DataFrame(rows).to_csv(out / "monthly.csv", index=False, encoding="utf-8-sig")
    summary = []
    for result in race.results:
        summary.append(
            {
                "id": result.id,
                "title": result.title,
                "train_cagr": result.train.cagr,
                "train_excess": result.train.mean_excess,
                "train_dd": result.train.max_dd,
                "train_invested": result.train.n_invested,
                "train_names": result.train.avg_names,
                "train_bench_cagr": result.train.bench_cagr,
                "test_cagr": result.test.cagr,
                "test_excess": result.test.mean_excess,
                "test_dd": result.test.max_dd,
                "test_invested": result.test.n_invested,
                "test_names": result.test.avg_names,
                "test_bench_cagr": result.test.bench_cagr,
                "test_hit": result.test.hit_rate,
            }
        )
    pd.DataFrame(summary).to_csv(out / "summary.csv", index=False, encoding="utf-8-sig")
    payload = {
        "as_of": race.as_of,
        "names": race.names,
        "ready_from": race.ready_from,
        "winner_id": race.winner_id,
        "confirmed": race.confirmed,
        "verdict": race.verdict,
        "note": race.note,
        "fund_coverage": race.fund_coverage,
        "results": [
            {
                "id": item.id,
                "title": item.title,
                "summary": item.summary,
                "train": asdict(item.train),
                "test": asdict(item.test),
            }
            for item in race.results
        ],
    }
    (out / "race.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# スクリーニング案の比較",
        "",
        f"- 基準日: {race.as_of}",
        f"- 3年指標が揃い始めた月: {race.ready_from or '未確認'}",
        f"- 銘柄数: {len(race.names)}",
        f"- 相対: 1306（TOPIX連動ETF）。指数そのものではない。",
        f"- {race.fund_coverage}",
        f"- {race.note}",
        "",
        f"**{race.verdict}**",
        "",
        "| 案 | 学習CAGR | 学習超過 | 学習DD | 学習投資月 | 学習平均銘柄 | 確認CAGR | 確認超過 | 確認DD | 確認投資月 | 確認平均銘柄 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in race.results:
        mark = ""
        if result.id == race.winner_id:
            mark = " 採用" if race.confirmed else " 学習最大"
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
    lines.extend(["", "## 案の定義", ""])
    for result in race.results:
        lines.append(f"- {result.title}: {result.summary}")
    lines.append("")
    (out / "race.md").write_text("\n".join(lines), encoding="utf-8")


def _bar_frame(root: Path, ticker: str) -> pd.DataFrame | None:
    candidates = (
        root / f"{ticker}_1d.pkl",
        root / "trend_screen" / "bars" / f"{ticker}.pkl",
    )
    for path in candidates:
        if not path.exists():
            continue
        frame = pd.read_pickle(path)
        frame.index = pd.to_datetime(frame.index)
        if "close" in frame.columns:
            return frame
    return None


def _load_bars(tickers: list[str]) -> tuple[dict[str, pd.Series], dict[str, pd.Series], pd.Series]:
    from signalforge.config import data_dir

    root = data_dir()
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    missing: list[str] = []
    for ticker in tickers:
        frame = _bar_frame(root, ticker)
        if frame is None:
            missing.append(ticker)
            continue
        closes[ticker] = frame["close"]
        if "volume" in frame.columns:
            volumes[ticker] = frame["volume"]
    bench_frame = _bar_frame(root, BENCHMARK)
    if bench_frame is None:
        raise FileNotFoundError(f"{BENCHMARK} の日足がありません。")
    if missing:
        print(f"missing bars {len(missing)}: {missing[:8]}", flush=True)
    return closes, volumes, bench_frame["close"]


def _load_funds(tickers: list[str], *, fetch_missing: bool = False) -> dict[str, list[AnnualPoint]]:
    from signalforge.config import data_dir
    from signalforge.research.trend_screen.load import load_annuals

    fins = data_dir() / "trend_screen" / "fins"
    out: dict[str, list[AnnualPoint]] = {}
    for i, ticker in enumerate(tickers, start=1):
        cached = fins / f"{ticker.replace('/', '_')}.json"
        if not fetch_missing and not cached.exists():
            continue
        try:
            annuals, _source = load_annuals(ticker, refresh=False)
        except Exception as exc:
            print(f"fund skip {ticker}: {exc}", flush=True)
            continue
        if annuals:
            out[ticker] = annuals
        if i % 25 == 0 or i == len(tickers):
            print(f"funds {i}/{len(tickers)} ready={len(out)}", flush=True)
    return out


def run_cached_race(*, limit: int = 300, fetch_funds: bool = True) -> tuple[Race, Path]:
    from signalforge.config import data_dir
    from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

    write_liquid_list(limit)
    names = read_liquid_list(limit)
    print(f"race universe={len(names)}", flush=True)
    closes, volumes, bench = _load_bars(names)
    fund_map: dict[str, list[AnnualPoint]] = {}
    if fetch_funds:
        fund_map = _load_funds(sorted(closes), fetch_missing=False)
    race = run_race(closes, volumes, bench, names=sorted(closes), fund_map=fund_map)
    out = data_dir() / "reports" / "trend_screen" / "race" / race.as_of
    write_race(race, out)
    print(race.fund_coverage, flush=True)
    print(race.verdict, flush=True)
    for result in race.results:
        flag = " *" if result.id == race.winner_id else ""
        print(
            f"{result.title}{flag} train CAGR {result.train.cagr:+.2%} "
            f"excess {result.train.mean_excess:+.2%} | "
            f"test CAGR {result.test.cagr:+.2%} excess {result.test.mean_excess:+.2%}",
            flush=True,
        )
    print(f"出力: {out / 'race.md'}", flush=True)
    return race, out
