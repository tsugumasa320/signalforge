"""PEG。予想と過去実績を混ぜない。成長率がゼロ以下なら算出しない。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from signalforge.research.trend_screen.config import HISTORICAL_VALUATION_MAX, VALUATION_MAX
from signalforge.research.trend_screen.fundamentals import AnnualPoint


@dataclass
class ValuationScore:
    peg: float | None = None
    status: str = "未確認"
    score: float | None = None
    max_points: float = 0.0
    per: float | None = None
    per_kind: str = "未確認"
    growth_pct: float | None = None
    growth_kind: str = "未確認"
    growth_span: str = "未確認"
    formula: str = "未確認"
    source: str = ""
    notes: list[str] = field(default_factory=list)


def historical_eps_cagr(annuals: list[AnnualPoint]) -> tuple[float | None, str]:
    series = [(row.fiscal_end, row.eps) for row in annuals if row.eps is not None]
    series = series[-6:]
    if len(series) < 4:
        return None, "EPSの通期が4期未満"
    if any(value <= 0 for _, value in series):
        return None, "期間内のEPSにゼロ以下がある"
    start_day = date.fromisoformat(series[0][0][:10])
    end_day = date.fromisoformat(series[-1][0][:10])
    years = (end_day - start_day).days / 365.25
    if years < 2.5:
        return None, "EPSの観測期間が2.5年未満"
    cagr = (series[-1][1] / series[0][1]) ** (1 / years) - 1
    if cagr > 1.5:
        return None, "EPS成長率が150%超。単位変更や一時要因の可能性があり未確認"
    span = f"{series[0][0][:10]} → {series[-1][0][:10]}（{years:.1f}年、{len(series)}期）"
    return cagr, span


def _band_points(peg: float) -> float:
    if peg < 0.5:
        return 6.0
    if peg < 1.0:
        return 10.0
    if peg <= 1.5:
        return 12.0
    if peg <= 2.0:
        return 9.0
    if peg <= 2.5:
        return 6.0
    return 2.0


def _trailing_per(price: float | None, eps: float | None) -> tuple[float | None, str]:
    if price is None or eps is None or price <= 0 or eps <= 0:
        return None, "実績PERは未確認"
    per = price / eps
    if per < 0.5 or per > 500:
        return None, "実績PERが異常値。EPSと株価の単位が合っていない可能性があり未確認"
    return per, "実績PER（直近通期EPSで株価を割った値）"


def score_valuation(
    *,
    price: float | None,
    annuals: list[AnnualPoint],
    forecast_per: float | None = None,
    forecast_growth_pct: float | None = None,
    forecast_horizon_years: float | None = None,
    forecast_source: str | None = None,
    source: str,
) -> ValuationScore:
    result = ValuationScore(source=source)
    cagr, span = historical_eps_cagr(annuals)
    trailing, trailing_kind = _trailing_per(price, annuals[-1].eps if annuals else None)
    forecast_ok = (
        forecast_per is not None
        and forecast_per > 0
        and forecast_growth_pct is not None
        and forecast_horizon_years is not None
        and forecast_horizon_years >= 2
        and 0.5 <= forecast_per <= 500
    )
    if forecast_growth_pct is not None and (forecast_horizon_years is None or forecast_horizon_years < 2):
        result.notes.append(
            f"予想EPS成長率{forecast_growth_pct:.1f}%は、予測期間が2年以上と確認できないためPEGに使っていない。"
        )
    if forecast_ok and forecast_growth_pct is not None and forecast_growth_pct <= 0:
        result.status = "算出不能"
        result.per = forecast_per
        result.per_kind = "予想PER"
        result.growth_pct = forecast_growth_pct
        result.growth_kind = "予想EPS成長率"
        result.growth_span = f"{forecast_horizon_years:.0f}年" if forecast_horizon_years else "未確認"
        result.score = 0.0
        result.max_points = VALUATION_MAX
        result.formula = "予想EPS成長率がゼロ以下のためPEGは算出不能。"
        result.source = forecast_source or source
        return result
    if forecast_ok and forecast_growth_pct is not None and forecast_per is not None:
        peg = forecast_per / forecast_growth_pct
        reliability = 3.0
        result.peg = peg
        result.status = "予想PEG"
        result.per = forecast_per
        result.per_kind = "予想PER"
        result.growth_pct = forecast_growth_pct
        result.growth_kind = "予想EPS成長率"
        result.growth_span = f"{forecast_horizon_years:.0f}年"
        result.score = round(_band_points(peg) + reliability, 2)
        result.max_points = VALUATION_MAX
        result.formula = (
            f"PEG = 予想PER {forecast_per:.2f} ÷ 予想EPS成長率 {forecast_growth_pct:.2f}% = {peg:.2f}"
            f"（予測期間 {forecast_horizon_years:.0f}年、出典: {forecast_source or source}）"
        )
        result.source = forecast_source or source
        return result

    result.notes.append("2〜3年の予想EPS成長率は未確認。予想PEGは出していない。")
    if cagr is None or trailing is None:
        result.status = "未確認"
        result.notes.append(span if cagr is None else trailing_kind)
        result.formula = "予想PEGも過去PEGも未確認。"
        return result
    growth_pct = cagr * 100.0
    if growth_pct <= 0:
        result.status = "算出不能"
        result.per = trailing
        result.per_kind = trailing_kind
        result.growth_pct = growth_pct
        result.growth_kind = "過去EPS CAGR"
        result.growth_span = span
        result.score = 0.0
        result.max_points = HISTORICAL_VALUATION_MAX
        result.formula = f"過去EPS CAGRが{growth_pct:.2f}%のためPEGは算出不能。{trailing_kind} {trailing:.2f}。"
        return result
    peg = trailing / growth_pct
    points = _band_points(peg) * (10.0 / 12.0) + 2.0
    result.peg = peg
    result.status = "過去PEG"
    result.per = trailing
    result.per_kind = trailing_kind
    result.growth_pct = growth_pct
    result.growth_kind = "過去EPS CAGR"
    result.growth_span = span
    result.score = round(points, 2)
    result.max_points = HISTORICAL_VALUATION_MAX
    result.formula = (
        f"過去PEG = 実績PER {trailing:.2f} ÷ 過去EPS CAGR {growth_pct:.2f}% = {peg:.2f}"
        f"（{span}）。予想PEGではない。信頼性の3点は加点していない。"
    )
    return result
