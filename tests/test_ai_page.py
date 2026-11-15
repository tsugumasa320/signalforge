"""GitHub Pages AI trial export."""

from __future__ import annotations

import json
from pathlib import Path

from signalforge.ai.publish import save_response
from signalforge.report.ai_page import export_ai_page, render_ai_body


def test_save_response_writes_published(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data" / "published").mkdir(parents=True)
    outs = save_response("brief", {"as_of": "2026-11-13", "market_take": "x", "watch": []})
    assert outs["published"].exists()
    assert "ai_brief_response.json" in str(outs["published"])
    assert json.loads(outs["published"].read_text(encoding="utf-8"))["as_of"] == "2026-11-13"


def test_export_ai_page(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(tmp_path / "data"))
    pub = tmp_path / "data" / "published"
    pub.mkdir(parents=True)
    save_response(
        "brief",
        {
            "as_of": "2026-11-13",
            "market_take": "テスト",
            "watch": [{"ticker": "7203.T", "name": "トヨタ", "stance": "WATCH", "confidence": 50}],
            "paper_notes": [],
            "skip_today": [],
            "actions_for_human": [],
        },
    )
    save_response("score", {"as_of": "2026-11-13", "scores": [], "adopted": [], "skipped_reasons": []})
    save_response(
        "debate",
        {
            "as_of": "2026-11-13",
            "debates": [
                {
                    "ticker": "7203.T",
                    "name": "トヨタ",
                    "bull": "b",
                    "bear": "e",
                    "risk_officer": "r",
                    "decision": "HOLD",
                    "confidence": 50,
                    "invalidation": "i",
                    "why_this_could_fail": "f",
                }
            ],
            "committee_summary": "summary",
        },
    )
    out = tmp_path / "_site"
    path = export_ai_page(out)
    html = path.read_text(encoding="utf-8")
    assert "AIトライアル" in html
    assert "7203.T" in html
    assert "テスト" in html
    assert (out / "ai" / "ai_brief_response.json").exists()


def test_render_ai_body_empty() -> None:
    html = render_ai_body(None, None, None)
    assert "未公開" in html
