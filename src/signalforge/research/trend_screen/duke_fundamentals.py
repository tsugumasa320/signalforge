"""DUKE向けファンダ・ゲートと目標株価（粗いEPS×PER）。

図56の中計ストーリー（市場規模・KPI分解）は対象外。
通期キャッシュから機械判定できる定量部分だけ扱う。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from signalforge.research.trend_screen.fundamentals import AnnualPoint, _yoy


FUND_GATE_KEYS = (
    "fund_data",
    "fund_sales_up",
    "fund_op_up",
    "fund_margin_ok",
    "fund_upside_pos",
)

FUND_GATE_LABELS = {
    "fund_data": "通期財務あり",
    "fund_sales_up": "売上YoYプラス",
    "fund_op_up": "営業利益YoYプラス",
    "fund_margin_ok": "営業利益率大きく悪化せず",
    "fund_upside_pos": "ファンダ目標＞現値",
}


@dataclass
class DukeFundSnapshot:
    has_data: bool = False
    sales_yoy: float | None = None
    op_yoy: float | None = None
    op_margin: float | None = None
    op_margin_delta: float | None = None
    eps: float | None = None
    eps_yoy: float | None = None
    trailing_per: float | None = None
    fwd_eps: float | None = None
    assumed_per: float | None = None
    target_price_fund: float | None = None
    upside_pct: float | None = None
    stop_price: float | None = None
    t1_price: float | None = None
    t2_price: float | None = None
    t3_price: float | None = None
    gates: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_row_fields(self) -> dict[str, Any]:
        return {
            "fund_sales_yoy": self.sales_yoy,
            "fund_op_yoy": self.op_yoy,
            "fund_op_margin": self.op_margin,
            "fund_op_margin_delta": self.op_margin_delta,
            "fund_eps": self.eps,
            "fund_eps_yoy": self.eps_yoy,
            "trailing_per": self.trailing_per,
            "fwd_eps": self.fwd_eps,
            "assumed_per": self.assumed_per,
            "target_price_fund": self.target_price_fund,
            "upside_pct": self.upside_pct,
            "stop_price": self.stop_price,
            "t1_price": self.t1_price,
            "t2_price": self.t2_price,
            "t3_price": self.t3_price,
            "fund_notes": self.notes[:3],
        }


def _assumed_per(growth: float | None) -> float:
    """成長率帯に応じた想定PER（成長株向けの粗い目安）。"""
    if growth is None or growth < 0:
        return 12.0
    if growth >= 0.30:
        return 28.0
    if growth >= 0.20:
        return 22.0
    if growth >= 0.10:
        return 18.0
    if growth >= 0.05:
        return 15.0
    return 12.0


def _latest_yoy(values: list[float | None]) -> float | None:
    series = _yoy(values)
    if not series:
        return None
    return series[-1]


def evaluate_duke_fundamentals(
    annuals: list[AnnualPoint] | None,
    *,
    price: float | None,
    box_height: float | None = None,
) -> DukeFundSnapshot:
    # T2: ボックス値幅を足す計測目標。無ければ +50% を代理
    if price and price > 0:
        if box_height is not None and box_height > 0:
            t2 = round(price + float(box_height), 2)
        else:
            t2 = round(price * 1.50, 2)
    else:
        t2 = None
    snap = DukeFundSnapshot(
        gates={k: False for k in FUND_GATE_KEYS},
        stop_price=round(price * 0.90, 2) if price and price > 0 else None,
        t1_price=round(price * 1.20, 2) if price and price > 0 else None,
        t2_price=t2,
        t3_price=round(price * 2.00, 2) if price and price > 0 else None,
    )
    ordered = sorted(annuals or [], key=lambda row: row.fiscal_end)
    usable = [row for row in ordered if row.sales is not None or row.operating_income is not None or row.eps is not None]
    if len(usable) < 2:
        snap.notes.append("通期が2期未満または欠損のためファンダ未判定")
        return snap

    snap.has_data = True
    snap.gates["fund_data"] = True
    snap.sales_yoy = _latest_yoy([row.sales for row in usable])
    snap.op_yoy = _latest_yoy([row.operating_income for row in usable])
    snap.eps_yoy = _latest_yoy([row.eps for row in usable])
    snap.eps = usable[-1].eps
    snap.op_margin = usable[-1].op_margin
    prev_m = usable[-2].op_margin if len(usable) >= 2 else None
    if snap.op_margin is not None and prev_m is not None:
        snap.op_margin_delta = snap.op_margin - prev_m

    snap.gates["fund_sales_up"] = bool(snap.sales_yoy is not None and snap.sales_yoy > 0)
    snap.gates["fund_op_up"] = bool(snap.op_yoy is not None and snap.op_yoy > 0)
    # 利益率が2pt超悪化していなければOK（改善・横ばい含む）
    snap.gates["fund_margin_ok"] = bool(
        snap.op_margin_delta is None or snap.op_margin_delta >= -0.02
    )

    if price and price > 0 and snap.eps is not None and snap.eps > 0:
        per = price / snap.eps
        if 0.5 <= per <= 500:
            snap.trailing_per = per

    growth_candidates = [g for g in (snap.sales_yoy, snap.op_yoy, snap.eps_yoy) if g is not None]
    growth = max(growth_candidates) if growth_candidates else None
    snap.assumed_per = _assumed_per(growth)

    if snap.eps is not None and snap.eps > 0:
        g = growth if growth is not None else 0.0
        # 外挿は年率50%でキャップ（異常値抑制）
        g_use = max(-0.2, min(0.50, g))
        snap.fwd_eps = snap.eps * (1.0 + g_use)
        snap.target_price_fund = snap.fwd_eps * float(snap.assumed_per)
        if price and price > 0:
            snap.upside_pct = snap.target_price_fund / price - 1.0
            snap.gates["fund_upside_pos"] = bool(snap.upside_pct > 0)
        snap.notes.append(
            f"目標≈予想EPS {snap.fwd_eps:.2f} × 想定PER {snap.assumed_per:.0f}"
            + (f"（成長目安 {growth:.0%}）" if growth is not None else "")
        )
    else:
        snap.notes.append("EPS欠損のためファンダ目標株価は未算出")

    if box_height is not None and box_height > 0 and price and price > 0:
        snap.notes.append(f"T2=現値+ボックス値幅({box_height:.2f})")
    elif price and price > 0:
        snap.notes.append("T2=現値×1.5（ボックス値幅なしの代理）")

    return snap
