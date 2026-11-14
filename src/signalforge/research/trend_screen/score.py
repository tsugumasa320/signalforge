"""チャート・業績・バリュエーションを合算する。銘柄コードでは加点しない。"""

from __future__ import annotations

from dataclasses import dataclass, field

from signalforge.research.trend_screen.chart import ChartMetrics
from signalforge.research.trend_screen.config import CHART_MAX, LIQUIDITY_YEN
from signalforge.research.trend_screen.fundamentals import FundamentalScore
from signalforge.research.trend_screen.valuation import ValuationScore


def _interp(x: float, anchors: list[tuple[float, float]]) -> float:
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return anchors[-1][1]


def _interp_desc(x: float, anchors: list[tuple[float, float]]) -> float:
    if x >= anchors[0][0]:
        return anchors[0][1]
    if x <= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x1 <= x <= x0:
            if x0 == x1:
                return y0
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return anchors[-1][1]


@dataclass
class ChartScore:
    components: dict[str, float | None] = field(default_factory=dict)
    score: float | None = None
    max_points: float = 0.0
    notes: list[str] = field(default_factory=list)


def score_chart(metrics: ChartMetrics) -> ChartScore:
    result = ChartScore()
    if not metrics.reliable_daily:
        result.notes.append("日足ではないため、チャート点は未確認。")
        return result
    result.components = {
        "ret_3y": None if metrics.ret_3y is None else _interp(metrics.ret_3y, [(0.0, 0.0), (0.5, 4.0), (1.0, 6.0), (2.0, 8.0)]),
        "ret_1y": None if metrics.ret_1y is None else _interp(metrics.ret_1y, [(0.0, 0.0), (0.2, 3.0), (0.4, 6.0)]),
        "ma200_slope": None
        if metrics.ma200_slope is None
        else _interp(metrics.ma200_slope, [(0.0, 0.0), (0.08, 6.0)]),
        "ma75_slope": None if metrics.ma75_slope is None else _interp(metrics.ma75_slope, [(0.0, 0.0), (0.04, 4.0)]),
        "above_ma200": None
        if metrics.pct_above_ma200 is None
        else (0.0 if metrics.pct_above_ma200 < 0.50 else _interp(metrics.pct_above_ma200, [(0.50, 0.0), (0.70, 4.0), (0.85, 6.0)])),
        "mdd_3y": None
        if metrics.mdd_3y is None
        else _interp_desc(metrics.mdd_3y, [(0.0, 10.0), (-0.15, 10.0), (-0.25, 8.0), (-0.35, 5.0), (-0.50, 2.0), (-0.70, 0.0)]),
        "mdd_1y": None
        if metrics.mdd_1y is None
        else _interp_desc(metrics.mdd_1y, [(0.0, 4.0), (-0.10, 4.0), (-0.25, 2.0), (-0.40, 0.0)]),
        "excess_1y": None if metrics.excess_1y is None else _interp(metrics.excess_1y, [(0.0, 0.0), (0.15, 4.0)]),
        "up_months": None
        if metrics.up_month_ratio is None
        else (2.0 if metrics.up_month_ratio >= 0.65 else 1.0 if metrics.up_month_ratio >= 0.55 else 0.0),
    }
    core = ("ret_3y", "ret_1y", "ma200_slope", "ma75_slope", "above_ma200", "mdd_3y", "mdd_1y", "up_months")
    if any(result.components[name] is None for name in core):
        result.notes.append("チャートの中核指標が足りないため、チャート点は未確認。")
        return result
    earned = sum(float(result.components[name]) for name in core)
    maximum = sum(CHART_MAX[name] for name in core)
    if result.components["excess_1y"] is None:
        result.notes.append("TOPIX相対は未確認。4点は加点していない。")
    else:
        earned += float(result.components["excess_1y"])
        maximum += CHART_MAX["excess_1y"]
    result.score = round(earned, 2)
    result.max_points = maximum
    return result


def candidate_status(ma200_rising: bool | None, total: float | None, error: str | None) -> str:
    if error:
        return "取得失敗"
    if ma200_rising is False:
        return "原則除外"
    if total is None:
        return "総合点未確定"
    return "選定対象"


def grade(total: float | None, ma200_rising: bool | None) -> str:
    if total is None:
        base = "総合点未確定"
    elif total >= 85:
        base = "最優先候補"
    elif total >= 75:
        base = "有力候補"
    elif total >= 65:
        base = "監視候補"
    else:
        base = "原則見送り"
    if ma200_rising is False and total is not None:
        return f"{base}（200日線が下向きのため新規候補から除外）"
    return base


def primary_label(primary: dict[str, bool | None]) -> str:
    known = [value for value in primary.values() if value is not None]
    if not known:
        return "未確認"
    hits = sum(1 for value in known if value)
    text = f"{hits}/{len(known)}"
    if len(known) != len(primary):
        text += "（未確認あり）"
    return text


@dataclass
class ScoredName:
    code: str
    name: str
    market: str = "未確認"
    sector: str = "未確認"
    market_cap: float | None = None
    candidate_status: str = "総合点未確定"
    grade: str = "総合点未確定"
    total: float | None = None
    total_max: float | None = None
    flags: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    price_rise_note: str = ""
    pullback: str = ""
    trend_break: str = ""
    chart: ChartMetrics | None = None
    chart_score: ChartScore | None = None
    fundamentals: FundamentalScore | None = None
    valuation: ValuationScore | None = None
    error: str | None = None
    price_source: str = ""
    fundamental_source: str = ""
    in_listing: bool | None = None


def _flags(metrics: ChartMetrics, fund: FundamentalScore, val: ValuationScore) -> list[str]:
    flags: list[str] = []
    if metrics.primary.get("ma200_rising_60") is False:
        flags.append("200日線が下向き")
    elif metrics.primary.get("price_above_ma200") is False:
        flags.append("終値が200日線以下")
    if metrics.prefer.get("mdd_3y_within_35") is False:
        flags.append("3年間の最大ドローダウンが大きい")
    if metrics.prefer.get("mdd_1y_within_25") is False:
        flags.append("1年間の最大ドローダウンが大きい")
    if metrics.prefer.get("above_ma200_70") is False:
        flags.append("200日線より上にある日が70%未満")
    if metrics.prefer.get("within_20_of_52w") is False:
        flags.append("52週高値から20%超下落")
    if metrics.turnover_20d is not None and metrics.turnover_20d < LIQUIDITY_YEN:
        flags.append("流動性が不足")
    if fund.components.get("eps") == 0:
        flags.append("EPSが増加傾向ではない")
    if fund.components.get("sales") == 0:
        flags.append("売上が増加傾向ではない")
    if fund.components.get("op") == 0:
        flags.append("営業利益が増加傾向ではない")
    if val.status == "算出不能":
        flags.append("EPS成長率がゼロ以下")
    if val.peg is not None and val.peg > 2.5:
        flags.append("PEGが高すぎる")
    if metrics.primary.get("ret_3y_positive") is False:
        flags.append("3年リターンがマイナス")
    if metrics.primary.get("ret_1y_positive") is False:
        flags.append("1年リターンがマイナス")
    if metrics.primary.get("topix_excess_1y") is False:
        flags.append("過去1年はTOPIXを下回る")
    return flags


def _strengths(metrics: ChartMetrics, fund: FundamentalScore, val: ValuationScore) -> list[str]:
    found: list[str] = []
    if metrics.mdd_3y is not None and metrics.mdd_3y >= -0.25:
        found.append(f"3年の終値ドローダウンは{metrics.mdd_3y:.1%}。")
    if metrics.pct_above_ma200 is not None and metrics.pct_above_ma200 >= 0.70:
        found.append(f"200日線より上にあった営業日は{metrics.pct_above_ma200:.0%}。")
    if metrics.ret_3y is not None and metrics.ret_1y is not None and metrics.ret_3y > 0 and metrics.ret_1y > 0:
        found.append(f"株価リターンは3年{metrics.ret_3y:+.1%}、1年{metrics.ret_1y:+.1%}。")
    if metrics.excess_1y is not None and metrics.excess_1y > 0:
        found.append(f"過去1年のTOPIX相対は{metrics.excess_1y:+.1%}。")
    if all(fund.components.get(name) == 7 for name in ("sales", "op", "eps")):
        found.append("売上・営業利益・EPSはいずれも直近の通期で増加方向。")
    if val.status == "予想PEG" and val.peg is not None and val.peg <= 1.5:
        found.append(f"予想PEGは{val.peg:.2f}。")
    return found


def _risks(metrics: ChartMetrics, fund: FundamentalScore, val: ValuationScore, flags: list[str]) -> list[str]:
    risks = list(flags)
    risks.extend(fund.penalties)
    if val.status == "過去PEG":
        risks.append("バリュエーションは過去PEG。予想PEGは未確認。")
    if val.status == "未確認":
        risks.append("PEGは未確認。")
    if metrics.vol_1y is not None and metrics.vol_1y >= 0.45:
        risks.append(f"1年の年率ボラティリティは{metrics.vol_1y:.0%}。")
    return risks


def _rise_note(metrics: ChartMetrics, fund: FundamentalScore) -> str:
    ret = "未確認" if metrics.ret_3y is None else f"{metrics.ret_3y:+.1%}"
    excess = "未確認" if metrics.excess_1y is None else f"{metrics.excess_1y:+.1%}"
    grew = all(fund.components.get(name) not in (None, 0) for name in ("sales", "op", "eps"))
    direction = "通期の売上・営業利益・EPSは増加方向" if grew else "通期業績の増加は確認できないか、未確認"
    window = metrics.ret_3y_start or "未確認"
    return (
        f"株価が上昇した原因は断定しない。観測できるのは、{window}からの株価リターンが{ret}、"
        f"過去1年のTOPIX相対が{excess}、{direction}、という事実だけ。"
    )


def _pullback(metrics: ChartMetrics) -> str:
    def yen(value: float | None) -> str:
        if value is None:
            return "未確認"
        return f"{value:,.0f}円"

    return f"25日線 {yen(metrics.ma25)}、75日線 {yen(metrics.ma75)}、終値 {yen(metrics.price)}。"


def _trend_break(metrics: ChartMetrics) -> str:
    ma = "未確認" if metrics.ma200 is None else f"{metrics.ma200:,.0f}円"
    return f"終値が200日線（{ma}）を下回り、200日線の60営業日変化がマイナスになること。"


def assemble(
    *,
    code: str,
    name: str,
    market: str,
    sector: str,
    market_cap: float | None,
    metrics: ChartMetrics,
    fund: FundamentalScore,
    val: ValuationScore,
    price_source: str,
    in_listing: bool | None,
    error: str | None = None,
) -> ScoredName:
    chart_score = score_chart(metrics)
    total = None
    total_max = None
    if chart_score.score is not None and fund.score is not None and val.score is not None:
        total = round(chart_score.score + fund.score + val.score, 2)
        total_max = round(chart_score.max_points + fund.max_points + val.max_points, 2)
    rising = metrics.primary.get("ma200_rising_60")
    flags = [] if error else _flags(metrics, fund, val)
    if in_listing is False:
        flags.append("上場一覧の内国普通株に見つからない")
    row = ScoredName(
        code=code,
        name=name,
        market=market,
        sector=sector,
        market_cap=market_cap,
        candidate_status=candidate_status(rising, total, error),
        grade=grade(total, rising),
        total=total,
        total_max=total_max,
        flags=flags,
        strengths=[] if error else _strengths(metrics, fund, val),
        risks=[] if error else _risks(metrics, fund, val, flags),
        price_rise_note="" if error else _rise_note(metrics, fund),
        pullback="" if error else _pullback(metrics),
        trend_break="" if error else _trend_break(metrics),
        chart=metrics,
        chart_score=chart_score,
        fundamentals=fund,
        valuation=val,
        error=error,
        price_source=price_source,
        fundamental_source=fund.source,
        in_listing=in_listing,
    )
    return row


def ranked(rows: list[ScoredName], limit: int = 30) -> list[ScoredName]:
    pool = [row for row in rows if row.candidate_status == "選定対象" and row.total is not None]
    pool.sort(
        key=lambda row: (
            -float(row.total or 0),
            -float(row.chart_score.score if row.chart_score and row.chart_score.score is not None else -1),
            row.code,
        )
    )
    return pool[:limit]
