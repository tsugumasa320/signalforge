"""JPX listing codes: alphanumeric domestic equities stay, non-equities stay out."""

import pandas as pd

from signalforge.alt_data.jquants_client import listing_code_to_jquants
from signalforge.universe.tse_listing import _parse_jpx_frame

_DOMESTIC = ("prime", "standard", "growth")


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _domestic(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("segment") in _DOMESTIC]


def test_alpha_prime_kept_and_trailing_zero_stripped() -> None:
    rows = _parse_jpx_frame(
        _frame(
            [
                {
                    "コード": "285A",
                    "銘柄名": "キオクシアホールディングス",
                    "市場・商品区分": "プライム（内国株式）",
                    "33業種区分": "電気機器",
                },
                {
                    "コード": "285A0",
                    "銘柄名": "キオクシアホールディングス",
                    "市場・商品区分": "プライム（内国株式）",
                    "33業種区分": "電気機器",
                },
            ]
        )
    )
    kept = _domestic(rows)
    assert [r["ticker"] for r in kept] == ["285A.T", "285A.T"]
    assert {r["code"] for r in kept} == {"285A"}
    assert "285A0.T" not in {r["ticker"] for r in rows}


def test_alpha_etf_and_pro_still_dropped() -> None:
    rows = _parse_jpx_frame(
        _frame(
            [
                {
                    "コード": "130A",
                    "銘柄名": "例ETF",
                    "市場・商品区分": "ETF・ETN",
                    "33業種区分": "-",
                },
                {
                    "コード": "141A",
                    "銘柄名": "例PRO",
                    "市場・商品区分": "PRO Market",
                    "33業種区分": "-",
                },
                {
                    "コード": "928A",
                    "銘柄名": "例REIT",
                    "市場・商品区分": "REIT・ベンチャーファンド・カントリーファンド・インフラファンド",
                    "33業種区分": "-",
                },
            ]
        )
    )
    assert rows
    assert all(r.get("segment") is None for r in rows)
    assert _domestic(rows) == []


def test_numeric_codes_unchanged() -> None:
    rows = _domestic(
        _parse_jpx_frame(
            _frame(
                [
                    {
                        "コード": 7203,
                        "銘柄名": "トヨタ自動車",
                        "市場・商品区分": "プライム（内国株式）",
                        "33業種区分": "輸送用機器",
                    },
                    {
                        "コード": 25935,
                        "銘柄名": "伊藤園第1種優先株式",
                        "市場・商品区分": "プライム（内国株式）",
                        "33業種区分": "食料品",
                    },
                ]
            )
        )
    )
    by_code = {r["code"]: r["ticker"] for r in rows}
    assert by_code["7203"] == "7203.T"
    assert by_code["25935"] == "25935.T"


def test_junk_codes_rejected() -> None:
    rows = _parse_jpx_frame(
        _frame(
            [
                {"コード": "ABCD", "銘柄名": "x", "市場・商品区分": "プライム（内国株式）"},
                {"コード": "28A5", "銘柄名": "x", "市場・商品区分": "プライム（内国株式）"},
                {"コード": "285I", "銘柄名": "x", "市場・商品区分": "プライム（内国株式）"},
                {"コード": "285O", "銘柄名": "x", "市場・商品区分": "プライム（内国株式）"},
                {"コード": "285A1", "銘柄名": "x", "市場・商品区分": "プライム（内国株式）"},
                {"コード": "285A00", "銘柄名": "x", "市場・商品区分": "プライム（内国株式）"},
            ]
        )
    )
    assert rows == []


def test_jquants_code_still_appends_zero_only_for_four_digit_numeric() -> None:
    assert listing_code_to_jquants("7203") == "72030"
    assert listing_code_to_jquants("25935") == "25935"
    assert listing_code_to_jquants("285A") == "285A"
