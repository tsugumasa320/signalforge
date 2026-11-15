"""Daily AI pipeline and adoption log/eval."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from signalforge.ai.adoption import append_adoptions_from_score, evaluate_adoptions, load_adoption_log
from signalforge.ai.auto import generate_score_response, score_candidate
from signalforge.ai.daily import run_daily


@pytest.fixture()
def sample_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    published = data / "published"
    paper = data / "paper"
    published.mkdir(parents=True)
    paper.mkdir()
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(data))

    ranking = {
        "system_id": "test",
        "version": "1",
        "name": "テスト",
        "as_of": "2026-11-13",
        "signal_date": "2026-11-13",
        "n_universe": 2,
        "n_pass": 2,
        "n_target": 1,
        "targets": [
            {
                "rank": 1,
                "ticker": "7203.T",
                "code": "7203",
                "name": "トヨタ",
                "price": 3000.0,
                "ret_1y": 0.4,
                "ret_20d": 0.05,
            }
        ],
        "ranking": [
            {
                "rank": 1,
                "ticker": "7203.T",
                "code": "7203",
                "name": "トヨタ",
                "price": 3000.0,
                "ret_1y": 0.4,
                "ret_20d": 0.05,
                "ret_60d": 0.1,
                "vol_1y": 0.25,
                "mdd_1y": -0.1,
                "turnover_20d": 2e10,
                "trend_r2": 0.8,
                "vs_ma25": 0.05,
                "target": True,
                "earnings_next_days": 40,
            },
            {
                "rank": 2,
                "ticker": "6758.T",
                "code": "6758",
                "name": "ソニー",
                "price": 4000.0,
                "ret_1y": 0.2,
                "ret_20d": 0.5,
                "vol_1y": 0.3,
                "mdd_1y": -0.1,
                "turnover_20d": 1e10,
                "trend_r2": 0.5,
                "vs_ma25": 0.02,
                "target": False,
                "earnings_next_days": 40,
            },
        ],
    }
    (published / "trend_screen_ranking.json").write_text(json.dumps(ranking), encoding="utf-8")
    (paper / "trend_screen.json").write_text(
        json.dumps(
            {
                "system_id": "test",
                "as_of": "2026-11-13",
                "open": {"open": True, "holdings": [], "month_excess": 0.0},
                "live": {},
                "summary": {},
            }
        ),
        encoding="utf-8",
    )

    # synthetic OHLCV for forward eval
    idx = pd.date_range("2026-11-13", periods=30, freq="B", tz="UTC")
    px = pd.DataFrame(
        {"open": 3000, "high": 3010, "low": 2990, "close": [3000 + i * 10 for i in range(30)], "volume": 1e6},
        index=idx,
    )
    cache_dir = data
    px.to_pickle(cache_dir / "7203.T_1d.pkl")
    return data


def test_score_candidate_skips_overheat() -> None:
    hot = score_candidate(
        {
            "ticker": "X.T",
            "ret_1y": 1.0,
            "ret_20d": 0.5,
            "vol_1y": 0.3,
            "mdd_1y": -0.1,
            "turnover_20d": 1e10,
            "trend_r2": 0.9,
            "vs_ma25": 0.1,
            "earnings_next_days": 40,
        }
    )
    assert hot["decision"] == "SKIP"


def test_generate_score_limits_adopt() -> None:
    packet = {
        "as_of": "2026-11-13",
        "candidates": [
            {
                "ticker": f"{i}.T",
                "name": str(i),
                "ret_1y": 0.8,
                "ret_20d": 0.05,
                "vol_1y": 0.2,
                "mdd_1y": -0.1,
                "turnover_20d": 2e10,
                "trend_r2": 0.8,
                "vs_ma25": 0.05,
                "earnings_next_days": 40,
            }
            for i in range(10)
        ],
    }
    resp = generate_score_response(packet, max_adopt=3)
    assert len(resp["adopted"]) <= 3
    assert resp["generator"] == "rules/v1"


def test_run_daily_and_eval(sample_data: Path) -> None:
    out = run_daily(score_top=2, debate_top=1, max_adopt=2, notify_discord=False)
    assert out["as_of"] == "2026-11-13"
    assert (sample_data / "published" / "ai_brief_response.json").exists()
    assert (sample_data / "published" / "ai_scores_response.json").exists()
    assert (sample_data / "published" / "ai_debate_response.json").exists()
    assert (sample_data / "published" / "ai_adoption_log.json").exists()
    log = load_adoption_log()
    assert len(log["entries"]) == 1
    # second run same as_of should not duplicate
    append_adoptions_from_score(
        json.loads((sample_data / "published" / "ai_scores_response.json").read_text(encoding="utf-8"))
    )
    assert len(load_adoption_log()["entries"]) == 1
    ev = evaluate_adoptions()
    assert ev["summary"]["n_adopted_rows"] >= 1
    # 5d should be evaluable with synthetic bars
    assert ev["summary"]["n_eval_5d"] >= 1
