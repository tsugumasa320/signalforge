"""AI discovery: score the liquid universe without requiring trend-screen pass."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from signalforge.ai.auto import generate_score_response
from signalforge.ai.content import content_coverage, enrich_content_rows
from signalforge.ai.events import enrich_event_rows, event_coverage
from signalforge.ai.packet import load_trend_ranking, slim_rank_row, utc_now_iso, write_json
from signalforge.ai.paths import ai_dir, load_prompt
from signalforge.ai.publish import published_path, save_response
from signalforge.ai.score import RUBRIC

SCHEMA = "signalforge-ai-discover/v1"
PUBLISHED_NAME = "ai_discover_response.json"


def _universe_rows(ranking_raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ranking_raw.get("universe") or []
    if rows:
        return list(rows)
    # Fallback: passed + rejected
    return list(ranking_raw.get("ranking") or []) + list(ranking_raw.get("rejected") or [])


def build_discover_packet(
    *,
    limit: int = 300,
    min_turnover: float = 5e8,
    fetch_news: bool = False,
) -> dict[str, Any]:
    ranking_raw = load_trend_ranking()
    if not ranking_raw:
        raise FileNotFoundError(
            "data/published/trend_screen_ranking.json がありません。"
            "先に `uv run signalforge trend-screen ranking` を実行してください。"
        )
    as_of = ranking_raw.get("as_of") or ranking_raw.get("signal_date")
    as_of_s = str(as_of) if as_of else None

    passed = {
        str(r.get("ticker"))
        for r in (ranking_raw.get("ranking") or [])
        if r.get("ticker") and r.get("passed", True)
    }
    raw_rows = _universe_rows(ranking_raw)
    # Liquidity prefilter only — no trend-screen pass gate.
    filtered: list[dict[str, Any]] = []
    for r in raw_rows:
        turn = r.get("turnover_20d")
        if turn is not None and float(turn) < min_turnover:
            continue
        filtered.append(r)
    # Prefer higher turnover when truncating
    filtered.sort(key=lambda r: float(r.get("turnover_20d") or 0), reverse=True)
    filtered = filtered[: max(0, limit)]

    from signalforge.ai.pit import annotate_pit_rows, pit_coverage

    candidates = enrich_event_rows(
        [slim_rank_row(r) for r in filtered],
        as_of=as_of_s,
    )
    candidates = enrich_content_rows(candidates, as_of=as_of_s, fetch_news=fetch_news)
    candidates = annotate_pit_rows(candidates, as_of=as_of_s)
    for c in candidates:
        t = str(c.get("ticker") or "")
        c["screen_passed"] = t in passed

    return {
        "schema": SCHEMA,
        "generated_at": utc_now_iso(),
        "purpose": "universe_discovery",
        "market": "japan",
        "as_of": as_of,
        "system_id": ranking_raw.get("system_id"),
        "version": ranking_raw.get("version"),
        "rubric": RUBRIC,
        "pool": {
            "universe_size": len(raw_rows),
            "after_liquidity": len(filtered),
            "min_turnover": min_turnover,
            "limit": limit,
            "screen_passed_in_pool": sum(1 for c in candidates if c.get("screen_passed")),
        },
        "event_coverage": event_coverage(candidates),
        "content_coverage": content_coverage(candidates),
        "pit_coverage": pit_coverage(candidates),
        "notes": (
            "トレンド・スクリーニング通過は不要。"
            "流動性ユニバースから売買代金フィルタのみで母集団を作り、同じ5因子ルールで採点。"
            "screen_passed=false の ADOPT が『独自発掘』候補。"
            "PIT: as_of より後の内容は除外。"
        ),
        "candidates": candidates,
    }


def generate_discover_response(
    packet: dict[str, Any],
    *,
    max_adopt: int = 8,
) -> dict[str, Any]:
    resp = generate_score_response(packet, max_adopt=max_adopt)
    screen_map = {
        str(c.get("ticker")): bool(c.get("screen_passed"))
        for c in (packet.get("candidates") or [])
        if c.get("ticker")
    }
    for s in resp.get("scores") or []:
        t = str(s.get("ticker") or "")
        s["screen_passed"] = screen_map.get(t, False)

    adopted = list(resp.get("adopted") or [])
    only_discover = [t for t in adopted if not screen_map.get(t, False)]
    also_screen = [t for t in adopted if screen_map.get(t, False)]
    # Top discoveries among non-passers even if not ADOPT
    nonpass_scores = [
        s
        for s in (resp.get("scores") or [])
        if not s.get("screen_passed") and s.get("decision") in {"ADOPT", "WATCH"}
    ]
    nonpass_scores.sort(key=lambda s: float(s.get("total") or 0), reverse=True)

    resp["generator"] = "rules/discover-v1"
    resp["mode"] = "discover"
    resp["pool"] = packet.get("pool")
    resp["compare"] = {
        "adopted": adopted,
        "overlap_with_screen": also_screen,
        "discover_only": only_discover,
        "top_nonpass_watch": [
            {
                "ticker": s.get("ticker"),
                "name": s.get("name"),
                "total": s.get("total"),
                "decision": s.get("decision"),
            }
            for s in nonpass_scores[:10]
        ],
    }
    resp["skipped_reasons"] = list(resp.get("skipped_reasons") or []) + [
        "母集団はトレンド通過不要（流動性フィルタのみ）",
        "discover_only = ADOPT かつ screen_passed=false",
    ]
    # Keep published schema compatible with score page + extra compare
    return resp


def write_discover(
    *,
    limit: int = 300,
    min_turnover: float = 5e8,
    max_adopt: int = 8,
    fetch_news: bool = False,
    out_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    packet = build_discover_packet(
        limit=limit,
        min_turnover=min_turnover,
        fetch_news=fetch_news,
    )
    resp = generate_discover_response(packet, max_adopt=max_adopt)
    # attach prices
    price_map = {str(c.get("ticker")): c.get("price") for c in (packet.get("candidates") or [])}
    for s in resp.get("scores") or []:
        t = str(s.get("ticker") or "")
        if t and s.get("price") is None:
            s["price"] = price_map.get(t)

    base = out_dir or ai_dir()
    write_json(base / "discover_packet_latest.json", packet)
    write_json(base / "discover_response_latest.json", resp)
    pub = write_json(published_path(PUBLISHED_NAME), resp)
    # Also keep via save_response-compatible local copy is discover-specific
    return packet, resp, pub


def load_discover_response() -> dict[str, Any] | None:
    from signalforge.ai.packet import read_json
    from signalforge.config import ROOT

    for path in (
        published_path(PUBLISHED_NAME),
        ai_dir() / "discover_response_latest.json",
        ROOT / "examples" / "ai_discover_response.json",
    ):
        raw = read_json(path)
        if isinstance(raw, dict):
            return raw
    return None
