"""PIT visibility gate for AI content fields."""

from __future__ import annotations

from signalforge.ai.pit import annotate_pit, pit_coverage


def test_annotate_pit_strips_future_surprise_and_news() -> None:
    row = {
        "ticker": "7203.T",
        "earnings_last": "2026-10-01",
        "surprise": {
            "disc_date": "2026-11-20",
            "summary": "未来の開示",
            "c0": True,
        },
        "news": [
            {"title": "古い", "published_at": "2026-11-01"},
            {"title": "未来", "published_at": "2026-11-20"},
        ],
        "news_sentiment": "neutral",
        "content_data": "both",
    }
    out = annotate_pit(row, as_of="2026-11-13")
    assert out["pit_ok"] is False
    assert out["pit_status"] == "stripped"
    assert "surprise" not in out
    assert len(out.get("news") or []) == 1
    assert out["news"][0]["title"] == "古い"
    assert out["pit_available_at"] == "2026-11-01" or out["pit_available_at"] == "2026-10-01"
    assert any(i.startswith("surprise_after_as_of") for i in out["pit_issues"])
    assert any(i.startswith("news_after_as_of") for i in out["pit_issues"])


def test_annotate_pit_ok_when_content_on_or_before_as_of() -> None:
    row = {
        "ticker": "7203.T",
        "earnings_last": "2026-08-01",
        "surprise": {"disc_date": "2026-11-10", "summary": "ok", "c0": True},
        "news": [{"title": "見出し", "published_at": "2026-11-12T09:00:00Z"}],
        "content_data": "both",
    }
    out = annotate_pit(row, as_of="2026-11-13")
    assert out["pit_ok"] is True
    assert out["pit_status"] == "ok"
    assert out["surprise"]["disc_date"] == "2026-11-10"
    assert len(out["news"]) == 1
    cov = pit_coverage([out])
    assert cov["ok"] == 1
    assert cov["stripped"] == 0
