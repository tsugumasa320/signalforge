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
    assert "tip-mark" in html
    assert "tip-bubble" in html
    assert "基準日（最新）" in html


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


def test_yutai_month_merge_and_unknown_type():
    from signalforge.research.trend_screen.corporate_events import (
        _clean_yutai_type,
        _merge_yutai_months,
        _parse_month_nums,
    )

    assert _parse_month_nums("2・8月") == [2, 8]
    assert _parse_month_nums("3月・9月") == [3, 9]
    assert _merge_yutai_months("2月", "2・8月") == "2月・8月"
    assert _merge_yutai_months("9月", "3月・9月") == "3月・9月"
    assert _clean_yutai_type("記載なし") is None
    assert _clean_yutai_type("自社の優待券") == "自社の優待券"


def test_load_yutai_map_merges_meguri(tmp_path, monkeypatch):
    from signalforge.research.trend_screen import corporate_events as ce

    shirabe = tmp_path / "yutai-list.csv"
    shirabe.write_text(
        "\ufeffコード,会社名,市場,業種,権利確定月,基準日,必要株数,継続保有の条件,優待の種類,年額の推定（円）,会社ページのURL,有報の提出日\n"
        "8267,イオン,東証プライム,小売業,2月,2月末日,100,条件の記載なし,自社の優待券,,https://yutai-shirabe.com/c/8267.html,2026-01-01\n"
        "3391,ツルハHD,東証プライム,小売業,,,条件の記載なし,記載なし,,https://yutai-shirabe.com/c/3391.html,2026-01-01\n",
        encoding="utf-8",
    )
    meguri = tmp_path / "meguri-stock-stats.csv"
    meguri.write_text(
        "\ufeff証券コード,銘柄名,掲載店舗数,必要株数(最低),権利確定月,データ基準日\n"
        "8267,イオン,548,100,2・8月,2026-11-17\n"
        "3391,ツルハHD,6175,100,2月,2026-11-17\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ce, "yutai_list_path", lambda: shirabe)
    monkeypatch.setattr(ce, "yutai_meguri_stats_path", lambda: meguri)
    monkeypatch.setattr(ce, "ensure_yutai_list", lambda **kwargs: shirabe)
    monkeypatch.setattr(ce, "ensure_yutai_meguri_stats", lambda **kwargs: meguri)

    ymap = ce.load_yutai_map()
    assert ymap["8267"]["yutai_months"] == "2月・8月"
    assert ymap["8267"]["yutai_type"] == "自社の優待券"
    assert ymap["3391"]["yutai_months"] == "2月"
    assert ymap["3391"]["yutai_min_shares"] == 100
    assert ymap["3391"]["yutai_type"] is None
