"""Discord webhook message builder / notify skip behavior."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from signalforge.ai.discord_notify import build_daily_message, notify_daily, post_webhook


def test_build_daily_message_includes_adopt_and_actions() -> None:
    text = build_daily_message(
        as_of="2026-11-13",
        adopted=["7203.T", "6758.T"],
        brief_resp={
            "market_take": "テスト要約",
            "actions_for_human": ["チャート確認", "出口確認"],
            "skip_today": ["過熱追撃"],
        },
        eval_summary={"n_eval_5d": 2, "mean_ret_5d": 0.012},
    )
    assert "7203.T" in text
    assert "テスト要約" in text
    assert "チャート確認" in text
    assert "過熱追撃" in text
    assert "5日" in text
    assert "signalforge/ai/" in text


def test_notify_skips_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    out = notify_daily(as_of="2026-11-13", adopted=["7203.T"], brief_resp={})
    assert out["skipped"] is True
    assert out["ok"] is False


def test_post_webhook_posts_json() -> None:
    fake_resp = MagicMock()
    fake_resp.status = 204
    fake_resp.read.return_value = b""
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False
    with patch("urllib.request.urlopen", return_value=fake_resp) as mocked:
        result = post_webhook("https://discord.com/api/webhooks/test", "hello")
    assert result["ok"] is True
    req = mocked.call_args[0][0]
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["content"] == "hello"
