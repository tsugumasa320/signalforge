"""DUKE fund gates + EPS×PER target price."""

from __future__ import annotations

from signalforge.research.trend_screen.duke_fundamentals import evaluate_duke_fundamentals
from signalforge.research.trend_screen.fundamentals import AnnualPoint


def test_fund_gates_and_target_price():
    annuals = [
        AnnualPoint("2023-03-31", sales=100.0, operating_income=10.0, eps=50.0),
        AnnualPoint("2024-03-31", sales=120.0, operating_income=15.0, eps=60.0),
        AnnualPoint("2025-03-31", sales=150.0, operating_income=20.0, eps=80.0),
    ]
    snap = evaluate_duke_fundamentals(annuals, price=1000.0)
    assert snap.gates["fund_data"]
    assert snap.gates["fund_sales_up"]
    assert snap.gates["fund_op_up"]
    assert snap.gates["fund_margin_ok"]
    assert snap.target_price_fund is not None and snap.target_price_fund > 0
    assert snap.stop_price == 900.0
    assert snap.t1_price == 1200.0
    assert snap.upside_pct is not None


def test_missing_annuals():
    snap = evaluate_duke_fundamentals([], price=1000.0)
    assert not snap.gates["fund_data"]
    assert snap.target_price_fund is None
    assert snap.stop_price == 900.0


def test_box_measured_t2():
    snap = evaluate_duke_fundamentals(
        [AnnualPoint("2024-03-31", sales=100.0, operating_income=10.0, eps=50.0),
         AnnualPoint("2025-03-31", sales=120.0, operating_income=12.0, eps=60.0)],
        price=1000.0,
        box_height=80.0,
    )
    assert snap.t2_price == 1080.0


def test_midplan_card_builds():
    from signalforge.research.trend_screen.midplan_card import build_midplan_card

    card = build_midplan_card(
        ticker="7203.T",
        name="トヨタ",
        sector="輸送用機器",
        price=3000.0,
        annuals=[
            AnnualPoint("2024-03-31", sales=100.0, operating_income=10.0, eps=50.0),
            AnnualPoint("2025-03-31", sales=120.0, operating_income=15.0, eps=60.0),
        ],
        box_height=100.0,
    )
    assert any(c.id == "market_size" and c.status == "needs_human" for c in card.checks)
    assert card.targets["t2"] == 3100.0
    assert card.kpi_template
