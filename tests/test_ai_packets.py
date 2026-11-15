"""AI brief / score / debate packet builders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from signalforge.ai.brief import SCHEMA as BRIEF_SCHEMA
from signalforge.ai.brief import build_brief_packet, write_brief
from signalforge.ai.debate import SCHEMA as DEBATE_SCHEMA
from signalforge.ai.debate import build_debate_packet, write_debate
from signalforge.ai.score import SCHEMA as SCORE_SCHEMA
from signalforge.ai.score import build_score_packet, write_score


@pytest.fixture()
def sample_ranking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    published = data / "published"
    paper = data / "paper"
    ai = data / "ai"
    published.mkdir(parents=True)
    paper.mkdir()
    ai.mkdir()

    ranking = {
        "system_id": "test_sys",
        "version": "9.9",
        "name": "テスト",
        "as_of": "2026-11-13",
        "signal_date": "2026-11-13",
        "n_universe": 2,
        "n_pass": 2,
        "n_target": 1,
        "warning": None,
        "targets": [
            {
                "rank": 1,
                "ticker": "7203.T",
                "code": "7203",
                "name": "トヨタ",
                "price": 3000.0,
                "ret_1y": 0.2,
                "ret_20d": 0.01,
            }
        ],
        "ranking": [
            {
                "rank": 1,
                "ticker": "7203.T",
                "code": "7203",
                "name": "トヨタ",
                "sector": "輸送用機器",
                "market": "プライム",
                "price": 3000.0,
                "ret_1y": 0.2,
                "ret_20d": 0.01,
                "ret_60d": 0.05,
                "vol_1y": 0.2,
                "mdd_1y": -0.1,
                "dd_52w": -0.1,
                "turnover_20d": 1e10,
                "steady_score": 1.0,
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
                "sector": "電気機器",
                "market": "プライム",
                "price": 4000.0,
                "ret_1y": 0.1,
                "ret_20d": -0.02,
                "turnover_20d": 5e9,
                "target": False,
                "earnings_next_days": 5,
            },
        ],
    }
    (published / "trend_screen_ranking.json").write_text(
        json.dumps(ranking, ensure_ascii=False), encoding="utf-8"
    )
    (paper / "trend_screen.json").write_text(
        json.dumps(
            {
                "system_id": "test_sys",
                "version": "9.9",
                "name": "テスト",
                "as_of": "2026-11-13",
                "open": {
                    "open": True,
                    "signal_date": "2026-10-30",
                    "entry_date": "2026-11-02",
                    "month_net": 0.01,
                    "month_bench": 0.0,
                    "month_excess": 0.01,
                    "holdings": [
                        {
                            "ticker": "7203.T",
                            "code": "7203",
                            "name": "トヨタ",
                            "weight": 0.2,
                            "entry_price": 2900.0,
                            "mark_price": 3000.0,
                            "return": 0.034,
                        }
                    ],
                },
                "live": {"total_return": 1.0, "bench_total": 0.5, "value_jpy": 1e7},
                "summary": {
                    "cagr": 0.2,
                    "bench_cagr": 0.1,
                    "mean_excess": 0.02,
                    "max_dd": -0.2,
                    "hit_rate": 0.5,
                    "n_months": 12,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (paper / "diversified_swing_demo.json").write_text(
        json.dumps(
            {
                "style": "swing",
                "strategy": "demo",
                "cohort": "prime",
                "last_run_at": "2026-11-13",
                "initial_capital": 3_000_000,
                "last_sim": {
                    "final_equity": 3_100_000,
                    "total_return_pct": 3.33,
                    "max_drawdown_pct": -1.0,
                    "win_rate_pct": 50.0,
                    "accepted_trades": 2,
                    "fills": [
                        {
                            "ticker": "7203.T",
                            "entry_time": "2026-11-01",
                            "exit_time": "2026-11-10",
                            "pnl_pct": 2.0,
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (published / "tse_strategy_summary.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-11-13",
                "rows": [
                    {
                        "strategy_id": "demo",
                        "style": "swing",
                        "expectancy_pct": 0.5,
                        "profit_factor": 1.2,
                        "win_rate": 0.4,
                        "max_drawdown_pct": -10.0,
                        "portfolio": {
                            "total_return_pct": 20.0,
                            "oos_return_pct": 10.0,
                            "max_drawdown_pct": -12.0,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(data))
    return data


def test_build_brief_packet(sample_ranking: Path) -> None:
    packet = build_brief_packet(top=5)
    assert packet["schema"] == BRIEF_SCHEMA
    assert packet["sources"]["trend_screen_ranking"] is True
    assert packet["trend_screen"]["targets"][0]["ticker"] == "7203.T"
    assert packet["trend_paper"]["holdings"][0]["ticker"] == "7203.T"
    assert packet["diversified_papers"][0]["strategy"] == "demo"
    assert packet["tse_strategies"]["top_rows"][0]["strategy_id"] == "demo"


def test_write_brief_creates_prompt(sample_ranking: Path) -> None:
    packet, path, prompt_path = write_brief(top=5)
    assert path.exists()
    assert prompt_path.exists()
    assert "signalforge-ai-brief" in path.read_text(encoding="utf-8")
    assert "Packet" in prompt_path.read_text(encoding="utf-8")
    assert packet["schema"] == BRIEF_SCHEMA


def test_build_score_packet(sample_ranking: Path) -> None:
    packet = build_score_packet(top=2)
    assert packet["schema"] == SCORE_SCHEMA
    assert len(packet["candidates"]) == 2
    assert len(packet["rubric"]) == 5
    assert packet["candidates"][0]["ticker"] == "7203.T"


def test_write_score(sample_ranking: Path) -> None:
    packet, path, prompt_path = write_score(top=2)
    assert path.name == "scores_latest.json"
    assert (sample_ranking / "ai" / "scores_packet_20261113.json").exists()
    assert prompt_path.exists()
    assert packet["schema"] == SCORE_SCHEMA


def test_build_debate_from_targets(sample_ranking: Path) -> None:
    packet = build_debate_packet(top=1)
    assert packet["schema"] == DEBATE_SCHEMA
    assert packet["names"][0]["ticker"] == "7203.T"
    assert packet["names"][0]["metrics"]["name"] == "トヨタ"


def test_build_debate_from_scores_response(sample_ranking: Path) -> None:
    resp = {
        "as_of": "2026-11-13",
        "scores": [
            {"ticker": "6758.T", "total": 80, "decision": "ADOPT"},
            {"ticker": "7203.T", "total": 70, "decision": "WATCH"},
        ],
    }
    scores_path = sample_ranking / "ai" / "scores_response_latest.json"
    scores_path.write_text(json.dumps(resp), encoding="utf-8")
    packet = build_debate_packet(from_scores=True, top=1)
    assert packet["names"][0]["ticker"] == "6758.T"


def test_write_debate(sample_ranking: Path) -> None:
    packet, path, prompt_path = write_debate(tickers=["7203.T"])
    assert path.exists() and prompt_path.exists()
    assert packet["names"][0]["metrics"]["code"] == "7203"
