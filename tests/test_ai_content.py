"""Surprise + news content enrichment for AI packets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from signalforge.ai.auto import score_candidate
from signalforge.ai.content import (
    enrich_content_fields,
    load_latest_surprise,
    news_sentiment,
    save_news,
    ticker_to_jq_code,
)


def test_ticker_to_jq_code() -> None:
    assert ticker_to_jq_code("7203.T") == "72030"
    assert ticker_to_jq_code("72030") == "72030"


def test_news_sentiment_keywords() -> None:
    assert news_sentiment(["通期上方修正を発表"]) == "positive"
    assert news_sentiment(["下方修正で減益へ"]) == "negative"
    assert news_sentiment(["商品発表"]) == "neutral"


def test_score_candidate_uses_surprise_and_news() -> None:
    base = {
        "ticker": "7203.T",
        "name": "トヨタ",
        "ret_1y": 0.4,
        "ret_20d": 0.05,
        "vol_1y": 0.25,
        "mdd_1y": -0.1,
        "turnover_20d": 2e10,
        "trend_r2": 0.8,
        "vs_ma25": 0.05,
        "earnings_next_days": 40,
        "event_data": "ranking",
    }
    plain = score_candidate(base)
    boosted = score_candidate(
        {
            **base,
            "surprise": {
                "c0": True,
                "rev_op": True,
                "op_yoy": 0.25,
                "days_ago": 10,
                "summary": "C0合格",
            },
            "news_sentiment": "positive",
            "news": [{"title": "上方修正"}],
            "content_data": "both",
        }
    )
    assert boosted["factors"]["event"] > plain["factors"]["event"]
    assert "C0合格" in boosted["why"]

    bad = score_candidate(
        {
            **base,
            "surprise": {"c0": False, "op_yoy": -0.3, "days_ago": 5, "summary": "減益"},
            "news_sentiment": "negative",
            "news": [{"title": "下方修正"}],
            "content_data": "both",
        }
    )
    assert bad["factors"]["event"] < plain["factors"]["event"]


def test_enrich_content_from_news_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data" / "alt").mkdir(parents=True)
    save_news("7203.T", [{"title": "増益で最高益", "publisher": "test"}])
    row = enrich_content_fields({"ticker": "7203.T"}, as_of="2026-11-13", fetch_news=False)
    assert row["content_data"] in {"news", "both"}
    assert row["news_sentiment"] == "positive"
    assert row["news"][0]["title"].startswith("増益")


def test_load_latest_surprise_from_real_cache_if_present() -> None:
    # Optional integration: skip silently when sample fins missing.
    surprise = load_latest_surprise("6954.T", as_of="2026-11-13")  # 69540.parquet often in sample
    if surprise is None:
        pytest.skip("earnings_surprise fins sample not present")
    assert surprise.get("disc_date")
    assert "summary" in surprise
