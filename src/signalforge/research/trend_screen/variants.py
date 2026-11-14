"""同じ長期上昇トレンドから作った選別案。成績を見る前に固定する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from signalforge.research.trend_screen.chart import ChartMetrics
from signalforge.research.trend_screen.score import score_chart

PRIMARY_KEYS = (
    "price_above_ma200",
    "ma200_rising_60",
    "ma75_rising",
    "ret_1y_positive",
    "ret_3y_positive",
    "topix_excess_1y",
)


def passes_primary(metrics: ChartMetrics) -> bool:
    return all(metrics.primary.get(key) is True for key in PRIMARY_KEYS)


def passes_loose(metrics: ChartMetrics) -> bool:
    return (
        metrics.reliable_daily
        and metrics.primary.get("price_above_ma200") is True
        and metrics.primary.get("ma200_rising_60") is True
        and metrics.primary.get("ret_3y_positive") is True
    )


def _smooth(metrics: ChartMetrics) -> bool:
    return metrics.prefer.get("mdd_3y_within_35") is True and metrics.prefer.get("above_ma200_70") is True


def select_primary(book: dict[str, ChartMetrics]) -> list[str]:
    return sorted(code for code, metrics in book.items() if passes_primary(metrics))


def select_smooth(book: dict[str, ChartMetrics]) -> list[str]:
    return sorted(code for code, metrics in book.items() if passes_primary(metrics) and _smooth(metrics))


def select_chart_top5(book: dict[str, ChartMetrics]) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for code, metrics in book.items():
        if not passes_loose(metrics):
            continue
        score = score_chart(metrics).score
        if score is None:
            continue
        ranked.append((score, code))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [code for _, code in ranked[:5]]


def select_path_top5(book: dict[str, ChartMetrics]) -> list[str]:
    ranked: list[tuple[float, float, str]] = []
    for code, metrics in book.items():
        if not passes_loose(metrics) or metrics.mdd_3y is None:
            continue
        ranked.append((metrics.mdd_3y, metrics.pct_above_ma200 or -1.0, code))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [code for _, _, code in ranked[:5]]


def passes_entry(metrics: ChartMetrics, entry: str | None) -> bool:
    if entry is None:
        return True
    timing = metrics.timing
    if entry == "ppp":
        return timing == "ppp"
    if entry == "pullback":
        return timing in {"pullback_ma25", "pullback_ma75"}
    if entry == "ppp_or_pullback":
        return timing in {"ppp", "pullback_ma25", "pullback_ma75"}
    return False


@dataclass(frozen=True)
class Variant:
    id: str
    title: str
    summary: str
    select: Callable[[dict[str, ChartMetrics]], list[str]]
    # None=地合い無視 / above200 / uptrend
    regime: str | None = None
    # None=タイミング無視 / ppp / pullback / ppp_or_pullback
    entry: str | None = None
    require_fund: bool = False


def _v(
    id_: str,
    title: str,
    summary: str,
    select: Callable[[dict[str, ChartMetrics]], list[str]],
    *,
    regime: str | None = None,
    entry: str | None = None,
    require_fund: bool = False,
) -> Variant:
    return Variant(id_, title, summary, select, regime, entry, require_fund)


def catalog() -> tuple[Variant, ...]:
    """成績を見る前に固定した12案。確認期間の結果で増やさない。"""
    primary = "終値が200日線より上、200日線と75日線が上向き、1年と3年がプラス、1年で1306を上回る。"
    return (
        _v("gate_1y", "一次条件", primary, select_primary),
        _v(
            "gate_1y_above",
            "一次条件＋地合い(200上)",
            primary + " 1306が200日線より上の月だけ持つ。",
            select_primary,
            regime="above200",
        ),
        _v(
            "gate_1y_uptrend",
            "一次条件＋地合い(上昇)",
            primary + " 1306が200日線の上で、200日線が60営業日前より高い月だけ持つ。",
            select_primary,
            regime="uptrend",
        ),
        _v(
            "gate_1y_pullback",
            "一次条件＋押し目",
            primary + " 25日線または75日線付近の押し目の銘柄だけ買う。",
            select_primary,
            entry="pullback",
        ),
        _v(
            "gate_1y_ppp",
            "一次条件＋PPP",
            primary + " PPP成立の銘柄だけ買う。",
            select_primary,
            entry="ppp",
        ),
        _v(
            "gate_1y_up_pull",
            "地合い上昇＋押し目",
            primary + " 地合い上昇の月だけ。押し目の銘柄だけ買う。",
            select_primary,
            regime="uptrend",
            entry="pullback",
        ),
        _v(
            "gate_1y_fund",
            "一次条件＋業績増加",
            primary + " 当時利用可能とみなした通期で売上・営業利益・EPSが3期連続増加。",
            select_primary,
            require_fund=True,
        ),
        _v(
            "gate_1y_up_fund",
            "地合い上昇＋業績",
            primary + " 地合い上昇の月だけ。業績3期連続増加。",
            select_primary,
            regime="uptrend",
            require_fund=True,
        ),
        _v(
            "gate_1y_full",
            "地合い上昇＋押し目＋業績",
            primary + " 地合い上昇・押し目・業績増加をすべて満たす。",
            select_primary,
            regime="uptrend",
            entry="pullback",
            require_fund=True,
        ),
        _v(
            "rank_chart5",
            "チャート点の上位5",
            "200日線の上で上向き、3年プラスの中からチャート点の高い5銘柄。",
            select_chart_top5,
        ),
        _v(
            "rank_chart5_up",
            "チャート上位5＋地合い上昇",
            "チャート点上位5を、地合い上昇の月だけ持つ。",
            select_chart_top5,
            regime="uptrend",
        ),
        _v(
            "gate_smooth_up",
            "滑らかさ＋地合い上昇",
            primary + " 3年DD-35%以内かつ200日線上70%以上。地合い上昇の月だけ。",
            select_smooth,
            regime="uptrend",
        ),
    )
