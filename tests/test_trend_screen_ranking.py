"""Trend-screen published ranking helpers."""

from __future__ import annotations

from signalforge.report.trend_screen_page import render_trend_screen_body
from signalforge.research.trend_screen.ranking import GATE_LABELS


def test_render_trend_screen_body_contains_passers():
    payload = {
        "name": "テスト",
        "version": "1.2",
        "signal_date": "2026-10-30",
        "n_universe": 2,
        "n_on_signal": 2,
        "n_pass": 1,
        "n_target": 1,
        "top_n": 5,
        "warning": "",
        "targets": [{"code": "4588", "name": "オンコリス", "ret_1y": 1.0}],
        "ranking": [
            {
                "rank": 1,
                "code": "4588",
                "name": "オンコリス",
                "sector": "医薬品",
                "ret_1y": 1.0,
                "ret_20d": 0.1,
                "dd_52w": -0.04,
                "price": 7560.0,
                "turnover_20d": 1e10,
                "target": True,
            }
        ],
        "rejected": [
            {
                "code": "9999",
                "name": "落ち株",
                "ret_1y": 0.1,
                "ret_20d": -0.05,
                "fail_labels": [GATE_LABELS["ret_20d"]],
            }
        ],
        "rules_markdown": "# 規則\n\n## 選定\n\n- 上位 5\n",
    }
    html = render_trend_screen_body(payload)
    assert "4588" in html
    assert "オンコリス" in html
    assert "通過銘柄ランキング" in html
    assert "直近20日下落なし" in html
