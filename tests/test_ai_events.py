"""AI event enrichment from alt-data earnings cache (no live API)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from signalforge.ai.auto import score_candidate
from signalforge.ai.events import enrich_event_fields, enrich_event_rows, event_coverage
from signalforge.ai.score import build_score_packet


def _write_earnings(data: Path, ticker: str, dates: list[str]) -> None:
    path = data / "alt" / "earnings" / f"{ticker}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ticker": ticker,
                "earnings_dates": dates,
                "event_dates": dates,
                "source": "fixture",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def ranking_with_null_earnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    published = data / "published"
    published.mkdir(parents=True)
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(data))

    # Near earnings for 6758; far for 7203; empty cache for 9984 → missing
    _write_earnings(
        data,
        "6758.T",
        ["2025-08-01", "2025-11-01", "2026-11-18", "2027-02-01"],
    )
    _write_earnings(
        data,
        "7203.T",
        ["2025-05-01", "2025-08-01", "2026-12-20"],
    )
    _write_earnings(data, "9984.T", [])

    ranking = {
        "system_id": "test",
        "version": "1",
        "name": "イベント補完テスト",
        "as_of": "2026-11-13",
        "signal_date": "2026-11-13",
        "n_universe": 3,
        "n_pass": 3,
        "n_target": 1,
        "targets": [
            {
                "rank": 1,
                "ticker": "7203.T",
                "code": "7203",
                "name": "トヨタ",
                "price": 3000.0,
                "ret_1y": 0.3,
                "ret_20d": 0.04,
                "earnings_next": None,
                "earnings_next_days": None,
            }
        ],
        "ranking": [
            {
                "rank": 1,
                "ticker": "7203.T",
                "code": "7203",
                "name": "トヨタ",
                "price": 3000.0,
                "ret_1y": 0.3,
                "ret_20d": 0.04,
                "ret_60d": 0.08,
                "vol_1y": 0.25,
                "mdd_1y": -0.1,
                "turnover_20d": 2e10,
                "trend_r2": 0.8,
                "vs_ma25": 0.05,
                "target": True,
                "earnings_next": None,
                "earnings_next_days": None,
            },
            {
                "rank": 2,
                "ticker": "6758.T",
                "code": "6758",
                "name": "ソニー",
                "price": 4000.0,
                "ret_1y": 0.2,
                "ret_20d": 0.03,
                "vol_1y": 0.3,
                "mdd_1y": -0.12,
                "turnover_20d": 1e10,
                "trend_r2": 0.6,
                "vs_ma25": 0.02,
                "target": False,
                # ranking null → must come from alt cache
                "earnings_next": None,
                "earnings_next_days": None,
            },
            {
                "rank": 3,
                "ticker": "9984.T",
                "code": "9984",
                "name": "ソフトバンクG",
                "price": 5000.0,
                "ret_1y": 0.1,
                "ret_20d": 0.02,
                "vol_1y": 0.4,
                "mdd_1y": -0.2,
                "turnover_20d": 8e9,
                "trend_r2": 0.5,
                "vs_ma25": 0.01,
                "target": False,
                "earnings_next": None,
                "earnings_next_days": None,
            },
        ],
    }
    (published / "trend_screen_ranking.json").write_text(
        json.dumps(ranking, ensure_ascii=False), encoding="utf-8"
    )
    return data


def test_enrich_from_alt_cache(ranking_with_null_earnings: Path) -> None:
    row = {
        "ticker": "6758.T",
        "earnings_next": None,
        "earnings_next_days": None,
    }
    out = enrich_event_fields(row, as_of="2026-11-13")
    assert out["earnings_next"] == "2026-11-18"
    assert out["earnings_next_days"] == 5
    assert out["earnings_last"] == "2025-11-01"
    assert out["event_data"] == "alt_cache"


def test_enrich_keeps_ranking_values(ranking_with_null_earnings: Path) -> None:
    row = {
        "ticker": "6758.T",
        "earnings_next": "2026-12-01",
        "earnings_next_days": 18,
    }
    out = enrich_event_fields(row, as_of="2026-11-13")
    assert out["earnings_next"] == "2026-12-01"
    assert out["earnings_next_days"] == 18
    assert out["event_data"] == "ranking"


def test_enrich_missing_when_empty_cache(ranking_with_null_earnings: Path) -> None:
    out = enrich_event_fields({"ticker": "9984.T"}, as_of="2026-11-13")
    assert out["earnings_next"] is None
    assert out["earnings_next_days"] is None
    assert out["event_data"] == "missing"


def test_build_score_packet_enriches_candidates(ranking_with_null_earnings: Path) -> None:
    packet = build_score_packet(top=3)
    by_ticker = {c["ticker"]: c for c in packet["candidates"]}
    assert by_ticker["6758.T"]["earnings_next"] == "2026-11-18"
    assert by_ticker["6758.T"]["earnings_next_days"] == 5
    assert by_ticker["6758.T"]["event_data"] == "alt_cache"
    assert by_ticker["7203.T"]["earnings_next"] == "2026-12-20"
    assert by_ticker["7203.T"]["earnings_next_days"] == 37
    assert by_ticker["9984.T"]["event_data"] == "missing"
    cov = packet["event_coverage"]
    assert cov["with_earnings_next"] == 2
    assert cov["from_alt_cache"] == 2
    assert cov["missing"] == 1


def test_score_candidate_near_earnings_skip() -> None:
    near = score_candidate(
        {
            "ticker": "6758.T",
            "ret_1y": 0.5,
            "ret_20d": 0.05,
            "vol_1y": 0.25,
            "mdd_1y": -0.1,
            "turnover_20d": 1e10,
            "trend_r2": 0.8,
            "vs_ma25": 0.05,
            "earnings_next": "2026-11-18",
            "earnings_next_days": 5,
            "event_data": "alt_cache",
        }
    )
    assert near["decision"] == "SKIP"
    assert near["factors"]["event"] == 6
    assert "earnings_next=2026-11-18" in near["risk"]


def test_score_candidate_missing_vs_known_blank() -> None:
    missing = score_candidate(
        {
            "ticker": "9984.T",
            "ret_1y": 0.5,
            "ret_20d": 0.05,
            "vol_1y": 0.25,
            "mdd_1y": -0.1,
            "turnover_20d": 1e10,
            "trend_r2": 0.8,
            "vs_ma25": 0.05,
            "earnings_next_days": None,
            "event_data": "missing",
        }
    )
    assert missing["factors"]["event"] == 12
    known_blank = score_candidate(
        {
            "ticker": "9147.T",
            "ret_1y": 0.5,
            "ret_20d": 0.05,
            "vol_1y": 0.25,
            "mdd_1y": -0.1,
            "turnover_20d": 1e10,
            "trend_r2": 0.8,
            "vs_ma25": 0.05,
            "earnings_last": "2026-05-01",
            "earnings_next_days": None,
            "event_data": "alt_cache",
        }
    )
    assert known_blank["factors"]["event"] == 16
    far = score_candidate(
        {
            "ticker": "7203.T",
            "ret_1y": 0.5,
            "ret_20d": 0.05,
            "vol_1y": 0.25,
            "mdd_1y": -0.1,
            "turnover_20d": 1e10,
            "trend_r2": 0.8,
            "vs_ma25": 0.05,
            "earnings_next_days": 40,
            "event_data": "alt_cache",
        }
    )
    assert far["factors"]["event"] == 17


def test_event_coverage_helper() -> None:
    rows = enrich_event_rows(
        [
            {"ticker": "A", "earnings_next": "2026-12-01", "earnings_next_days": 10, "event_data": "ranking"},
            {"ticker": "B", "event_data": "missing"},
        ]
    )
    cov = event_coverage(rows)
    assert cov["n"] == 2
    assert cov["with_earnings_next"] == 1
