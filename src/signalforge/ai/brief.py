from __future__ import annotations

from pathlib import Path
from typing import Any

from signalforge.ai.packet import (
    load_trend_ranking,
    summarize_diversified_papers,
    summarize_ranking,
    summarize_trend_paper,
    summarize_tse_strategies,
    utc_now_iso,
    write_json,
)
from signalforge.ai.paths import ai_dir, load_prompt


SCHEMA = "signalforge-ai-brief/v1"


def build_brief_packet(
    *,
    top: int = 15,
    diversified_limit: int = 8,
    strategy_limit: int = 10,
) -> dict[str, Any]:
    ranking_raw = load_trend_ranking()
    sources: dict[str, Any] = {
        "trend_screen_ranking": bool(ranking_raw),
        "trend_screen_paper": False,
        "diversified_paper": False,
        "tse_strategy_summary": False,
    }
    packet: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": utc_now_iso(),
        "purpose": "daily_brief",
        "market": "japan",
        "sources": sources,
        "trend_screen": summarize_ranking(ranking_raw, top) if ranking_raw else None,
        "trend_paper": summarize_trend_paper(),
        "diversified_papers": summarize_diversified_papers(diversified_limit),
        "tse_strategies": summarize_tse_strategies(strategy_limit),
        "response_schema": {
            "as_of": "string|null",
            "market_take": "string",
            "watch": [
                {
                    "ticker": "string",
                    "name": "string",
                    "stance": "WATCH|LONG_CANDIDATE|REDUCE|AVOID",
                    "confidence": "0-100",
                    "why": "string",
                    "risk": "string",
                }
            ],
            "paper_notes": ["string"],
            "skip_today": ["string"],
            "actions_for_human": ["string"],
        },
    }
    sources["trend_screen_paper"] = packet["trend_paper"] is not None
    sources["diversified_paper"] = bool(packet["diversified_papers"])
    sources["tse_strategy_summary"] = packet["tse_strategies"] is not None
    return packet


def write_brief(
    *,
    top: int = 15,
    diversified_limit: int = 8,
    strategy_limit: int = 10,
    out_dir: Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    packet = build_brief_packet(
        top=top,
        diversified_limit=diversified_limit,
        strategy_limit=strategy_limit,
    )
    base = out_dir or ai_dir()
    packet_path = write_json(base / "brief_latest.json", packet)
    prompt = load_prompt("ai_brief.md")
    prompt_path = base / "brief_prompt.md"
    prompt_path.write_text(
        prompt
        + "\n\n---\n\n## Packet\n\n"
        + f"Read `{packet_path}` (schema `{SCHEMA}`) and reply in the response_schema JSON.\n",
        encoding="utf-8",
    )
    return packet, packet_path, prompt_path
