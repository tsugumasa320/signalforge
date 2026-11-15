from __future__ import annotations

from pathlib import Path
from typing import Any

from signalforge.ai.content import content_coverage, enrich_content_rows
from signalforge.ai.events import enrich_event_rows, event_coverage
from signalforge.ai.packet import (
    load_trend_ranking,
    slim_rank_row,
    utc_now_iso,
    write_json,
)
from signalforge.ai.paths import ai_dir, load_prompt
from signalforge.ai.pit import annotate_pit_rows, pit_coverage

SCHEMA = "signalforge-ai-score/v1"

RUBRIC = [
    {
        "id": "trend",
        "label": "トレンド整合",
        "max_points": 20,
        "hint": "ret_1y・vs_ma25・trend_r2。上昇トレンドが明確なら高得点。",
    },
    {
        "id": "momentum",
        "label": "モメンタム",
        "max_points": 20,
        "hint": "ret_20d・ret_60d。過熱（短期急騰のみ）は減点。健全な継続なら加点。",
    },
    {
        "id": "risk",
        "label": "リスク",
        "max_points": 20,
        "hint": "vol_1y・mdd_1y・dd_52w。ドローダウンやボラが大きいほど減点。",
    },
    {
        "id": "liquidity",
        "label": "流動性",
        "max_points": 20,
        "hint": "turnover_20d。執行しやすいほど加点。",
    },
    {
        "id": "event",
        "label": "イベント／内容",
        "max_points": 20,
        "hint": (
            "カレンダー: earnings_next_days（近いほど減点、missing は中立）。"
            "内容: surprise（会社予想上方/C0・営業利益YoY）と news 見出しキーワードで微調整。"
            "コンセンサス比ではない（J-Quants 短信ベース）。"
            "as_of より後の開示・見出しは PIT ゲートで除外。"
        ),
    },
]


def build_score_packet(*, top: int = 20, fetch_news: bool = False) -> dict[str, Any]:
    ranking_raw = load_trend_ranking()
    if not ranking_raw:
        raise FileNotFoundError(
            "data/published/trend_screen_ranking.json がありません。"
            "先に `uv run signalforge trend-screen ranking` を実行してください。"
        )
    as_of = ranking_raw.get("as_of") or ranking_raw.get("signal_date")
    as_of_s = str(as_of) if as_of else None
    candidates = enrich_event_rows(
        [slim_rank_row(r) for r in (ranking_raw.get("ranking") or [])[: max(0, top)]],
        as_of=as_of_s,
    )
    candidates = enrich_content_rows(candidates, as_of=as_of_s, fetch_news=fetch_news)
    candidates = annotate_pit_rows(candidates, as_of=as_of_s)
    return {
        "schema": SCHEMA,
        "generated_at": utc_now_iso(),
        "purpose": "candidate_score",
        "market": "japan",
        "as_of": as_of,
        "system_id": ranking_raw.get("system_id"),
        "version": ranking_raw.get("version"),
        "rubric": RUBRIC,
        "event_coverage": event_coverage(candidates),
        "content_coverage": content_coverage(candidates),
        "pit_coverage": pit_coverage(candidates),
        "event_notes": (
            "event 因子 = カレンダー + 内容。"
            "カレンダー: ranking / data/alt/earnings。"
            "サプライズ: data/earnings_surprise/fins（会社予想・YoY。コンセンサスなし）。"
            "ニュース: data/alt/news（Yahoo見出しキャッシュ。`ai score --fetch-news` で取得）。"
            "PIT: as_of より後の disc_date / published_at は除外（完全な歴史PIT認証ではない）。"
        ),
        "candidates": candidates,
        "response_schema": {
            "as_of": "string|null",
            "scores": [
                {
                    "ticker": "string",
                    "name": "string",
                    "total": "0-100",
                    "decision": "ADOPT|WATCH|SKIP",
                    "factors": {
                        "trend": "0-20",
                        "momentum": "0-20",
                        "risk": "0-20",
                        "liquidity": "0-20",
                        "event": "0-20",
                    },
                    "why": "string",
                    "risk": "string",
                }
            ],
            "adopted": ["ticker"],
            "skipped_reasons": ["string"],
        },
    }


def write_score(
    *,
    top: int = 20,
    out_dir: Path | None = None,
    fetch_news: bool = False,
) -> tuple[dict[str, Any], Path, Path]:
    packet = build_score_packet(top=top, fetch_news=fetch_news)
    base = out_dir or ai_dir()
    stamp = (packet.get("as_of") or "unknown").replace("-", "")
    dated = write_json(base / f"scores_packet_{stamp}.json", packet)
    latest = write_json(base / "scores_latest.json", packet)
    prompt = load_prompt("ai_score.md")
    prompt_path = base / "score_prompt.md"
    prompt_path.write_text(
        prompt
        + "\n\n---\n\n## Packet\n\n"
        + f"Read `{latest}` (schema `{SCHEMA}`) and reply in the response_schema JSON.\n"
        + f"Also keep a dated copy at `{dated}`.\n",
        encoding="utf-8",
    )
    return packet, latest, prompt_path
