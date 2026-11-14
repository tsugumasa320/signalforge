"""通期の売上・利益・財務。欠測は点数にしない。"""

from __future__ import annotations

from dataclasses import dataclass, field

from signalforge.research.trend_screen.config import EQUITY_RATIO_EXEMPT, FUND_MAX


@dataclass
class AnnualPoint:
    fiscal_end: str
    sales: float | None = None
    operating_income: float | None = None
    eps: float | None = None
    net_income: float | None = None
    operating_cf: float | None = None
    equity: float | None = None
    assets: float | None = None

    @property
    def op_margin(self) -> float | None:
        if self.operating_income is None or self.sales is None or self.sales <= 0:
            return None
        return self.operating_income / self.sales

    @property
    def roe(self) -> float | None:
        if self.net_income is None or self.equity is None or self.equity <= 0:
            return None
        return self.net_income / self.equity

    @property
    def equity_ratio(self) -> float | None:
        if self.equity is None or self.assets is None or self.assets <= 0:
            return None
        ratio = self.equity / self.assets
        if ratio < 0 or ratio > 1:
            return None
        return ratio


@dataclass
class FundamentalScore:
    components: dict[str, float | None] = field(default_factory=dict)
    score: float | None = None
    max_points: float = 0.0
    notes: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    annuals: list[AnnualPoint] = field(default_factory=list)
    source: str = ""


def _yoy(values: list[float | None]) -> list[float | None]:
    out: list[float | None] = []
    for prev, cur in zip(values, values[1:]):
        if prev is None or cur is None or prev <= 0:
            out.append(None)
        else:
            out.append((cur - prev) / prev)
    return out


def _trend(values: list[float | None]) -> tuple[float | None, str]:
    if len(values) < 3:
        return None, "通期が3期未満"
    usable = values[-4:] if len(values) >= 4 else values
    if any(v is None for v in usable):
        return None, "欠損期がある"
    ups = sum(cur > prev for prev, cur in zip(usable, usable[1:]))
    steps = len(usable) - 1
    end_up = usable[-1] > usable[0]
    if ups == steps and end_up:
        return 7.0, f"直近{steps}期間はすべて増加"
    if end_up and ups >= max(1, steps - 1) and ups >= 2:
        return 5.0, "おおむね増加"
    if end_up and ups >= 1:
        return 3.0, "始点より終点は高いが、途中に減少がある"
    if end_up:
        return 2.0, "始点より終点が高い"
    return 0.0, "増加傾向ではない"


def _margin_points(annuals: list[AnnualPoint]) -> tuple[float | None, str]:
    rows = annuals[-4:] if len(annuals) >= 4 else annuals
    margins = [row.op_margin for row in rows]
    if len(rows) < 3 or any(m is None for m in margins):
        return None, "営業利益率は未確認"
    delta = margins[-1] - margins[0]  # type: ignore[operator]
    if delta >= -0.005:
        return 4.0, "営業利益率は維持または改善"
    if delta >= -0.02:
        return 2.0, "営業利益率は2ポイント未満の悪化"
    if delta >= -0.05:
        return 1.0, "営業利益率は2〜5ポイントの悪化"
    return 0.0, "営業利益率は5ポイント超の悪化"


def _roe_points(annuals: list[AnnualPoint]) -> tuple[float | None, str]:
    roe = annuals[-1].roe if annuals else None
    if roe is None:
        return None, "ROEは未確認。期末自己資本で割る概算で、期中平均ではない"
    if roe > 1:
        return None, "ROEが100%を超える。自己資本の歪みの可能性があり未確認"
    if roe >= 0.15:
        return 4.0, "ROEは15%以上（期末自己資本ベース）"
    if roe >= 0.10:
        return 3.0, "ROEは10%以上15%未満（期末自己資本ベース）"
    if roe >= 0.05:
        return 1.0, "ROEは5%以上10%未満（期末自己資本ベース）"
    return 0.0, "ROEは5%未満（期末自己資本ベース）"


def _ocf_points(annuals: list[AnnualPoint]) -> tuple[float | None, str]:
    flows = [row.operating_cf for row in annuals[-2:]]
    if not flows or flows[-1] is None:
        return None, "営業CFは未確認"
    latest = flows[-1]
    prior = flows[-2] if len(flows) == 2 else None
    if latest > 0 and prior is not None and prior > 0:
        return 3.0, "直近2期の営業CFはプラス"
    if latest > 0:
        return 2.0, "直近の営業CFはプラス"
    return 0.0, "直近の営業CFはプラスではない"


def _exempt(sector: str | None) -> bool | None:
    if not sector or sector == "未確認":
        return None
    return any(name in sector for name in EQUITY_RATIO_EXEMPT)


def _equity_points(annuals: list[AnnualPoint], sector: str | None) -> tuple[float | None, str]:
    kind = _exempt(sector)
    ratio = annuals[-1].equity_ratio if annuals else None
    if kind is None:
        return None, "業種が未確認のため、自己資本比率は点数化しない"
    if kind is True:
        return 2.0, f"{sector}は自己資本比率の一律基準で減点しない"
    if ratio is None:
        return None, "自己資本比率は未確認"
    if ratio >= 0.50:
        return 3.0, "自己資本比率は50%以上"
    if ratio >= 0.35:
        return 2.0, "自己資本比率は35%以上"
    if ratio >= 0.20:
        return 1.0, "自己資本比率は20%以上"
    return 0.0, "自己資本比率は20%未満"


def _penalties(annuals: list[AnnualPoint]) -> list[tuple[str, float]]:
    if len(annuals) < 3:
        return []
    sales = _yoy([row.sales for row in annuals])
    op = _yoy([row.operating_income for row in annuals])
    eps = _yoy([row.eps for row in annuals])
    found: list[tuple[str, float]] = []
    if sales and op and sales[-1] is not None and op[-1] is not None:
        if sales[-1] < 0.05 and op[-1] > 0.30:
            found.append(("売上の伸びが小さいのに営業利益だけ急増", 4.0))
    if len(eps) >= 2 and eps[-1] is not None and eps[-2] is not None:
        if eps[-1] < 0 and eps[-2] > 0.10:
            found.append(("直近通期のEPS成長が失速", 3.0))
    flows = [row.operating_cf for row in annuals[-2:]]
    if len(flows) == 2 and flows[0] is not None and flows[1] is not None and flows[0] < 0 and flows[1] < 0:
        found.append(("営業CFが2期連続でマイナス", 2.0))
    margins = [row.op_margin for row in (annuals[-4:] if len(annuals) >= 4 else annuals)]
    if len(margins) >= 3 and margins[0] is not None and margins[-1] is not None and margins[-1] - margins[0] < -0.05:
        found.append(("営業利益率が5ポイント超悪化", 2.0))
    return found


def score_fundamentals(
    annuals: list[AnnualPoint],
    sector: str | None,
    *,
    source: str,
) -> FundamentalScore:
    ordered = sorted(annuals, key=lambda row: row.fiscal_end)
    result = FundamentalScore(annuals=ordered, source=source)
    result.notes.append("財務は取得時点の通期実績。遡及修正を含む可能性があり、過去時点のバックテストには使えない。")
    result.notes.append("ROEは期末自己資本で割った概算。期中平均ではない。")
    sales_pts, sales_note = _trend([row.sales for row in ordered])
    op_pts, op_note = _trend([row.operating_income for row in ordered])
    eps_pts, eps_note = _trend([row.eps for row in ordered])
    opm_pts, opm_note = _margin_points(ordered)
    roe_pts, roe_note = _roe_points(ordered)
    ocf_pts, ocf_note = _ocf_points(ordered)
    eq_pts, eq_note = _equity_points(ordered, sector)
    result.components = {
        "sales": sales_pts,
        "op": op_pts,
        "eps": eps_pts,
        "opm": opm_pts,
        "roe": roe_pts,
        "ocf": ocf_pts,
        "equity": eq_pts,
    }
    result.notes.extend([sales_note, op_note, eps_note, opm_note, roe_note, ocf_note, eq_note])
    core = ("sales", "op", "eps", "opm")
    if any(result.components[name] is None for name in core):
        result.notes.append("売上・営業利益・EPS・利益率のどれかが未確認のため、業績点は出さない。")
        return result
    labels = {"sales": "売上", "op": "営業利益", "eps": "EPS", "opm": "営業利益率", "roe": "ROE", "ocf": "営業CF", "equity": "自己資本"}
    earned = 0.0
    maximum = 0.0
    for name, points in result.components.items():
        if points is None:
            result.notes.append(f"{labels[name]}は未確認。その配点は加点していない。")
            continue
        earned += points
        maximum += FUND_MAX[name]
    for label, size in _penalties(ordered):
        earned -= size
        result.penalties.append(f"{label}（-{size:.0f}）")
    result.score = round(max(0.0, min(maximum, earned)), 2)
    result.max_points = maximum
    return result
