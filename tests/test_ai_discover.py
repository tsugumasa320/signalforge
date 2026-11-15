"""Universe discovery without trend-screen pass gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from signalforge.ai.discover import build_discover_packet, generate_discover_response, write_discover


@pytest.fixture()
def ranking_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    published = data / "published"
    published.mkdir(parents=True)
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(data))
    ranking = {
        "system_id": "test",
        "version": "1",
        "as_of": "2026-11-13",
        "signal_date": "2026-11-13",
        "ranking": [
            {
                "ticker": "7203.T",
                "code": "7203",
                "name": "トヨタ",
                "passed": True,
                "price": 3000,
                "ret_1y": 0.5,
                "ret_20d": 0.05,
                "vol_1y": 0.2,
                "mdd_1y": -0.1,
                "turnover_20d": 2e10,
                "trend_r2": 0.8,
                "vs_ma25": 0.05,
            }
        ],
        "universe": [
            {
                "ticker": "7203.T",
                "code": "7203",
                "name": "トヨタ",
                "passed": True,
                "price": 3000,
                "ret_1y": 0.5,
                "ret_20d": 0.05,
                "vol_1y": 0.2,
                "mdd_1y": -0.1,
                "turnover_20d": 2e10,
                "trend_r2": 0.8,
                "vs_ma25": 0.05,
            },
            {
                "ticker": "9984.T",
                "code": "9984",
                "name": "ソフトバンクG",
                "passed": False,
                "price": 8000,
                "ret_1y": 0.6,
                "ret_20d": 0.04,
                "vol_1y": 0.3,
                "mdd_1y": -0.15,
                "turnover_20d": 3e10,
                "trend_r2": 0.75,
                "vs_ma25": 0.03,
            },
            {
                "ticker": "1234.T",
                "code": "1234",
                "name": "低流動",
                "passed": False,
                "price": 100,
                "ret_1y": 1.0,
                "ret_20d": 0.05,
                "vol_1y": 0.2,
                "mdd_1y": -0.1,
                "turnover_20d": 1e7,
                "trend_r2": 0.9,
                "vs_ma25": 0.1,
            },
        ],
    }
    (published / "trend_screen_ranking.json").write_text(json.dumps(ranking), encoding="utf-8")
    return data


def test_discover_includes_nonpass(ranking_data: Path) -> None:
    packet = build_discover_packet(limit=10, min_turnover=5e8)
    tickers = {c["ticker"] for c in packet["candidates"]}
    assert "9984.T" in tickers
    assert "1234.T" not in tickers  # below min turnover
    assert any(c.get("screen_passed") is False for c in packet["candidates"])
    resp = generate_discover_response(packet, max_adopt=4)
    assert resp["mode"] == "discover"
    assert "compare" in resp
    _, out, path = write_discover(limit=10, min_turnover=5e8, max_adopt=4)
    assert path.exists()
    assert (ranking_data / "published" / "ai_discover_response.json").exists()
    assert out.get("compare") is not None
