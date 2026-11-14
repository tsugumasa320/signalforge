"""Trend-screen published ranking helpers."""

from __future__ import annotations

from signalforge.report.trend_screen_page import render_trend_screen_body
from signalforge.research.trend_screen.ranking import GATE_LABELS, LAB_GATE_KEYS


def test_render_trend_screen_body_contains_lab():
    payload = {
        "name": "テスト",
        "version": "1.2",
        "as_of": "2026-11-13",
        "signal_date": "2026-11-13",
        "rebalance_signal_date": "2026-10-30",
        "note": "基準日は最新営業日の終値。",
        "n_universe": 2,
        "n_on_signal": 2,
        "n_pass": 1,
        "n_target": 1,
        "top_n": 5,
        "warning": "",
        "lab_defaults": {
            "gates": {k: True for k in LAB_GATE_KEYS},
            "min_turnover": 5e7,
            "min_ret_20d": 0.0,
            "max_dd_52w": -0.15,
            "top_n": 5,
            "rank_by": "ret_1y",
        },
        "gate_labels": {k: GATE_LABELS[k] for k in LAB_GATE_KEYS},
        "targets": [{"code": "4588", "name": "オンコリス", "ret_1y": 1.0}],
        "universe": [
            {
                "code": "4588",
                "name": "オンコリス",
                "sector": "医薬品",
                "ret_1y": 1.0,
                "ret_20d": 0.1,
                "excess_1y": 0.5,
                "dd_52w": -0.04,
                "price": 7560.0,
                "turnover_20d": 1e10,
                "gates": {k: True for k in LAB_GATE_KEYS},
            }
        ],
        "ranking": [],
        "rejected": [],
        "rules_markdown": "# 規則\n\n## 選定\n\n- 上位 5\n",
    }
    html = render_trend_screen_body(payload, forward=None)
    assert "4588" in html
    assert "条件ラボ" in html
    assert "基準日" in html
    assert "2026-11-13" in html
    assert "2026-10-30" in html
    assert "data-gate=" in html
    assert "trend-lab-data" in html
    assert GATE_LABELS["ret_20d"] in html
    assert "finance.yahoo.co.jp" in html or "yahoo_jp_url" in html
    assert "決算・配当・優待" in html


def test_lab_gate_keys_cover_adopted_filters():
    assert "ret_20d" in LAB_GATE_KEYS
    assert "turnover" in LAB_GATE_KEYS
    assert "above_ma200" in LAB_GATE_KEYS


def test_yahoo_jp_url_and_earnings_around():
    from signalforge.research.trend_screen.corporate_events import (
        earnings_around,
        empty_event_fields,
        yahoo_jp_url,
    )

    assert yahoo_jp_url("8766.T") == "https://finance.yahoo.co.jp/quote/8766.T"
    assert yahoo_jp_url("8766") == "https://finance.yahoo.co.jp/quote/8766.T"
    empty = empty_event_fields("7203.T")
    assert empty["yahoo_jp_url"].endswith("7203.T")
    # キャッシュが無くてもキーは揃う
    ev = earnings_around("7203.T", "2026-11-13")
    assert "earnings_last" in ev and "earnings_next" in ev
