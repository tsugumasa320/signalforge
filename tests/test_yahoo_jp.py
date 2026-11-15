"""Shared Yahoo JP link helpers."""

from __future__ import annotations

from signalforge.report.yahoo_jp import normalize_tse_code, yahoo_jp_anchor, yahoo_jp_url


def test_yahoo_jp_url_and_anchor() -> None:
    assert yahoo_jp_url("7203.T") == "https://finance.yahoo.co.jp/quote/7203.T"
    assert yahoo_jp_url("7203") == "https://finance.yahoo.co.jp/quote/7203.T"
    assert normalize_tse_code("7203.T") == "7203"
    html = yahoo_jp_anchor("7203.T")
    assert "finance.yahoo.co.jp/quote/7203.T" in html
    assert "7203.T" in html
    assert yahoo_jp_anchor(None) == "—"
