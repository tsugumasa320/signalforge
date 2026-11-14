"""チャート一次条件だけの前方リターン。口座シミュレーションではない。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from signalforge.research.trend_screen.chart import evaluate_chart
from signalforge.research.trend_screen.config import FORWARD_HORIZONS, ROUND_TRIP_COST


@dataclass
class HorizonStat:
    horizon: int
    n: int
    mean_gross: float | None
    mean_net: float | None
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    mean_excess: float | None
    worst: float | None
    avg_names: float | None


@dataclass
class ForwardReport:
    strategy: str = "A"
    start: str | None = None
    end: str | None = None
    n_names: int = 0
    n_signal_dates: int = 0
    signal_dates: list[str] = field(default_factory=list)
    horizons: list[HorizonStat] = field(default_factory=list)
    note: str = ""


def _month_ends(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    last: dict[tuple[int, int], pd.Timestamp] = {}
    for stamp in index:
        last[(stamp.year, stamp.month)] = pd.Timestamp(stamp)
    return list(last.values())


def _passes(close: pd.Series, volume: pd.Series, benchmark: pd.Series | None, day: pd.Timestamp) -> bool:
    hist = close.loc[:day]
    vol = volume.loc[:day]
    bench = None if benchmark is None else benchmark.loc[:day]
    metrics = evaluate_chart(hist, vol, None, bench)
    return all(metrics.primary.get(key) is True for key in (
        "price_above_ma200",
        "ma200_rising_60",
        "ma75_rising",
        "ret_1y_positive",
        "ret_3y_positive",
        "topix_excess_1y",
    ))


def chart_forward(
    closes: dict[str, pd.Series],
    volumes: dict[str, pd.Series],
    benchmark: pd.Series | None,
) -> ForwardReport:
    report = ForwardReport(n_names=len(closes))
    report.note = (
        "戦略Aは長期チャートの一次条件をすべて満たす銘柄だけ。"
        "業績とPEGは使っていない。B・C・Dは、当時公表されていた財務が無いため未実施。"
        "これは等金額の口座曲線ではなく、銘柄と日付ごとの前方リターンの平均。"
        f"往復コストは一律{ROUND_TRIP_COST:.1%}の仮定。ポートフォリオの最大ドローダウンと回転率は未計算。"
        "指定銘柄は現存銘柄に限られ、生存者バイアスがある。全市場の検証ではない。"
    )
    if benchmark is None:
        report.note += " TOPIXが無いため、相対リターン条件を満たせず戦略Aの集計は空。"
        return report
    benchmark = benchmark.dropna().sort_index()
    benchmark = benchmark[~benchmark.index.duplicated(keep="last")]
    trades: dict[int, list[tuple[str, pd.Timestamp, float, float, float | None]]] = {h: [] for h in FORWARD_HORIZONS}
    dates: list[pd.Timestamp] = []
    for code, close in closes.items():
        px = close.dropna().sort_index()
        px = px[~px.index.duplicated(keep="last")]
        volume = volumes.get(code)
        if volume is None:
            continue
        vol = volume.reindex(px.index)
        for day in _month_ends(px.index):
            if not _passes(px, vol, benchmark, day):
                continue
            loc = px.index.get_loc(day)
            if not isinstance(loc, int):
                continue
            dates.append(day)
            for horizon in FORWARD_HORIZONS:
                exit_at = loc + 1 + horizon
                if exit_at >= len(px.index):
                    continue
                entry = float(px.iloc[loc + 1])
                exit_px = float(px.iloc[exit_at])
                if entry <= 0:
                    continue
                gross = exit_px / entry - 1.0
                excess = None
                entry_day = px.index[loc + 1]
                exit_day = px.index[exit_at]
                if entry_day in benchmark.index and exit_day in benchmark.index:
                    base = float(benchmark.loc[entry_day])
                    done = float(benchmark.loc[exit_day])
                    if base > 0:
                        excess = gross - (done / base - 1.0)
                trades[horizon].append((code, day, gross, gross - ROUND_TRIP_COST, excess))
    unique = sorted(set(dates))
    report.signal_dates = [day.date().isoformat() for day in unique]
    report.n_signal_dates = len(unique)
    if unique:
        report.start = unique[0].date().isoformat()
        report.end = unique[-1].date().isoformat()
    for horizon in FORWARD_HORIZONS:
        rows = trades[horizon]
        if not rows:
            report.horizons.append(HorizonStat(horizon, 0, None, None, None, None, None, None, None, None))
            continue
        nets = [row[3] for row in rows]
        grosses = [row[2] for row in rows]
        excesses = [row[4] for row in rows if row[4] is not None]
        wins = [value for value in nets if value > 0]
        losses = [value for value in nets if value <= 0]
        per_day: dict[pd.Timestamp, int] = {}
        for row in rows:
            per_day[row[1]] = per_day.get(row[1], 0) + 1
        name_counts = list(per_day.values())
        report.horizons.append(
            HorizonStat(
                horizon=horizon,
                n=len(rows),
                mean_gross=sum(grosses) / len(grosses),
                mean_net=sum(nets) / len(nets),
                win_rate=len(wins) / len(nets),
                avg_win=None if not wins else sum(wins) / len(wins),
                avg_loss=None if not losses else sum(losses) / len(losses),
                mean_excess=None if not excesses else sum(excesses) / len(excesses),
                worst=min(nets),
                avg_names=None if not name_counts else sum(name_counts) / len(name_counts),
            )
        )
    return report
