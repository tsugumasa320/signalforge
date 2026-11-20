"""Indicators, ranking, and weights. Trailing windows only."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from signalforge.research.stf.rules import SCORE_W20, SCORE_W60, StrategySpec


@dataclass(frozen=True)
class Snap:
    adj_o: float | None
    adj_c: float | None
    ret20: float | None
    ret60: float | None
    sma25: float | None
    sma75: float | None
    sma25_lag5: float | None
    sma75_lag5: float | None
    adv20: float | None
    raw_c: float | None = None


@dataclass(frozen=True)
class Target:
    weight: float
    month_weight: float
    halved: bool


def compute_indicators(df: pl.DataFrame) -> pl.DataFrame:
    """Add trailing indicators. ``df`` needs date, code, adj_c, va.

    Rolling windows are trailing (``center`` stays false). A later row
    cannot change an earlier indicator.
    """
    out = df.sort(["code", "date"])
    out = out.with_columns(
        [
            pl.col("adj_c").shift(20).over("code").alias("_c20"),
            pl.col("adj_c").shift(60).over("code").alias("_c60"),
            pl.col("adj_c").rolling_mean(25, min_samples=25).over("code").alias("sma25"),
            pl.col("adj_c").rolling_mean(75, min_samples=75).over("code").alias("sma75"),
            pl.col("va").fill_null(0.0).rolling_mean(20, min_samples=20).over("code").alias("adv20"),
        ]
    )
    out = out.with_columns(
        [
            (pl.col("adj_c") / pl.col("_c20") - 1.0).alias("ret20"),
            (pl.col("adj_c") / pl.col("_c60") - 1.0).alias("ret60"),
            pl.col("sma25").shift(5).over("code").alias("sma25_lag5"),
            pl.col("sma75").shift(5).over("code").alias("sma75_lag5"),
        ]
    )
    return out.drop(["_c20", "_c60"])


def _score(rel20: float, rel60: float, mode: str) -> float:
    if mode == "rel20":
        return rel20
    if mode == "rel60":
        return rel60
    return SCORE_W20 * rel20 + SCORE_W60 * rel60


def _passes_rel(rel20: float, rel60: float, mode: str) -> bool:
    if mode == "rel20":
        return rel20 > 0.0
    if mode == "rel60":
        return rel60 > 0.0
    return rel20 > 0.0 and rel60 > 0.0


def _skip_return(ret60: float, ret20: float) -> float:
    """Return from 60 bars ago to 20 bars ago. Recent month is left out."""
    denom = 1.0 + ret20
    if denom <= 0.0:
        return ret60
    return (1.0 + ret60) / denom - 1.0


def _sector_take(
    ranked: list[tuple[str, float, float, float]],
    spec: StrategySpec,
    sectors: dict[str, str] | None,
) -> list[tuple[str, float, float, float]]:
    if not spec.max_per_sector:
        return ranked[: spec.top_n]
    out: list[tuple[str, float, float, float]] = []
    counts: dict[str, int] = {}
    for row in ranked:
        sector = (sectors or {}).get(row[0], "")
        if counts.get(sector, 0) >= spec.max_per_sector:
            continue
        counts[sector] = counts.get(sector, 0) + 1
        out.append(row)
        if len(out) >= spec.top_n:
            break
    return out


def rank_candidates(
    rows: list[tuple[str, Snap]],
    bench_ret20: float | None,
    bench_ret60: float | None,
    spec: StrategySpec,
    *,
    sectors: dict[str, str] | None = None,
    markets: dict[str, str] | None = None,
    revisions: dict[str, str] | None = None,
) -> list[tuple[str, float, float, float]]:
    """Return ``(code, score, rel60, adv20)`` best-first.

    Empty when the benchmark return is missing: the filter cannot be applied.
    """
    if bench_ret20 is None or bench_ret60 is None:
        return []
    picked: list[tuple[str, float, float, float]] = []
    for code, snap in rows:
        close = snap.adj_c
        sma25 = snap.sma25
        sma75 = snap.sma75
        if (
            close is None
            or sma25 is None
            or sma75 is None
            or snap.ret20 is None
            or snap.ret60 is None
            or snap.adv20 is None
            or close <= 0.0
        ):
            continue
        if not (close > sma25 > sma75):
            continue
        if spec.require_slope:
            if snap.sma25_lag5 is None or snap.sma75_lag5 is None:
                continue
            if not (sma25 > snap.sma25_lag5 and sma75 > snap.sma75_lag5):
                continue
        if snap.adv20 < spec.min_adv:
            continue
        price = snap.raw_c if snap.raw_c is not None else close
        if price < spec.min_price:
            continue
        if spec.max_ret60 is not None and snap.ret60 > spec.max_ret60:
            continue
        if spec.markets is not None and (markets or {}).get(code) not in spec.markets:
            continue
        revision = (revisions or {}).get(code)
        if spec.earnings_mode == "raise_only" and revision != "up":
            continue
        if spec.earnings_mode == "drop_cut" and revision == "down":
            continue
        rel20 = snap.ret20 - bench_ret20
        rel60 = snap.ret60 - bench_ret60
        if not _passes_rel(rel20, rel60, spec.rel_filter):
            continue
        if spec.score_mode == "skip20":
            score = _skip_return(snap.ret60, snap.ret20) - _skip_return(bench_ret60, bench_ret20)
        else:
            score = _score(rel20, rel60, spec.score_mode)
        picked.append((code, score, rel60, snap.adv20))
    def _order(row: tuple[str, float, float, float]) -> tuple:
        raised = 1 if spec.earnings_mode == "raise_first" and (revisions or {}).get(row[0]) == "up" else 0
        return (-raised, -row[1], -row[2], -row[3], row[0])

    picked.sort(key=_order)
    return _sector_take(picked, spec, sectors)


def allocate(ranked: list[tuple[str, float, float, float]], spec: StrategySpec) -> dict[str, Target]:
    """Map codes to targets. Gross may be below ``leverage`` when the cap binds."""
    if not ranked:
        return {}
    codes = [row[0] for row in ranked]
    if spec.weighting == "equal":
        raw = {code: 1.0 / len(codes) for code in codes}
    else:
        scores = {row[0]: max(row[1], 0.0) for row in ranked}
        total = sum(scores.values())
        if total <= 0.0:
            return {}
        raw = {code: scores[code] / total for code in codes}
        raw = _cap_and_redistribute(raw, spec.name_cap)
    out: dict[str, Target] = {}
    for code, weight in raw.items():
        scaled = weight * spec.leverage
        if scaled <= 0.0:
            continue
        out[code] = Target(weight=scaled, month_weight=scaled, halved=False)
    return out


def _cap_and_redistribute(weights: dict[str, float], cap: float) -> dict[str, float]:
    w = dict(weights)
    capped: set[str] = set()
    for _ in range(len(w) + 1):
        over = [code for code, value in w.items() if code not in capped and value > cap + 1e-12]
        if not over:
            break
        excess = sum(w[code] - cap for code in over)
        for code in over:
            w[code] = cap
            capped.add(code)
        free = [code for code in w if code not in capped]
        free_sum = sum(w[code] for code in free)
        if free_sum <= 1e-15:
            break
        for code in free:
            w[code] += excess * (w[code] / free_sum)
    return w
