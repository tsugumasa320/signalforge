from __future__ import annotations

from pathlib import Path
from typing import Any

from signalforge.ai.packet import (
    load_trend_ranking,
    read_json,
    slim_rank_row,
    summarize_trend_paper,
    utc_now_iso,
    write_json,
)
from signalforge.ai.paths import ai_dir, load_prompt

SCHEMA = "signalforge-ai-debate/v1"


def _row_by_ticker(ranking: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    want = ticker.upper().replace(".T", "")
    for key in ("ranking", "targets"):
        for row in ranking.get(key) or []:
            code = str(row.get("code") or "").upper()
            sym = str(row.get("ticker") or "").upper().replace(".T", "")
            full = str(row.get("ticker") or "").upper()
            if code == want or sym == want or full == ticker.upper():
                return slim_rank_row(row)
    return None


def _tickers_from_scores(path: Path, *, limit: int) -> list[str]:
    raw = read_json(path)
    if not isinstance(raw, dict):
        return []
    scores = raw.get("scores")
    if isinstance(scores, list) and scores:
        adopted = [s.get("ticker") for s in scores if s.get("decision") == "ADOPT" and s.get("ticker")]
        if adopted:
            return [str(t) for t in adopted[:limit]]
        ordered = sorted(scores, key=lambda s: float(s.get("total") or 0), reverse=True)
        return [str(s["ticker"]) for s in ordered if s.get("ticker")][:limit]
    candidates = raw.get("candidates") or []
    return [str(c["ticker"]) for c in candidates if c.get("ticker")][:limit]


def resolve_debate_tickers(
    *,
    tickers: tuple[str, ...] | list[str],
    from_scores: bool,
    top: int,
    scores_path: Path | None = None,
) -> list[str]:
    if tickers:
        return [t.strip() for t in tickers if t.strip()]
    if from_scores:
        path = scores_path or (ai_dir() / "scores_response_latest.json")
        if not path.exists():
            path = ai_dir() / "scores_latest.json"
        found = _tickers_from_scores(path, limit=top)
        if found:
            return found
    ranking = load_trend_ranking()
    if not ranking:
        raise FileNotFoundError(
            "議論対象がありません。`--tickers` を指定するか "
            "`trend-screen ranking` / `ai score` を先に実行してください。"
        )
    targets = ranking.get("targets") or []
    if targets:
        return [str(t["ticker"]) for t in targets if t.get("ticker")][:top]
    return [str(r["ticker"]) for r in (ranking.get("ranking") or []) if r.get("ticker")][:top]


def build_debate_packet(
    *,
    tickers: tuple[str, ...] | list[str] = (),
    from_scores: bool = False,
    top: int = 3,
    scores_path: Path | None = None,
) -> dict[str, Any]:
    ranking = load_trend_ranking()
    if not ranking:
        raise FileNotFoundError(
            "data/published/trend_screen_ranking.json がありません。"
            "先に `uv run signalforge trend-screen ranking` を実行してください。"
        )
    chosen = resolve_debate_tickers(
        tickers=tickers,
        from_scores=from_scores,
        top=top,
        scores_path=scores_path,
    )
    names: list[dict[str, Any]] = []
    missing: list[str] = []
    for t in chosen:
        row = _row_by_ticker(ranking, t)
        if row is None:
            missing.append(t)
            names.append({"ticker": t, "metrics": None})
        else:
            names.append({"ticker": row.get("ticker") or t, "metrics": row})
    return {
        "schema": SCHEMA,
        "generated_at": utc_now_iso(),
        "purpose": "bull_bear_debate",
        "market": "japan",
        "as_of": ranking.get("as_of") or ranking.get("signal_date"),
        "system_id": ranking.get("system_id"),
        "note": (
            "TradingAgents は米国前提が多いため、日本株は SignalForge 自前の議論パケットを使う。"
            "発注には接続しない。参考意見のみ。"
        ),
        "context": {"trend_paper": summarize_trend_paper()},
        "names": names,
        "missing_from_ranking": missing,
        "response_schema": {
            "as_of": "string|null",
            "debates": [
                {
                    "ticker": "string",
                    "name": "string",
                    "bull": "string",
                    "bear": "string",
                    "risk_officer": "string",
                    "decision": "BUY|HOLD|AVOID",
                    "confidence": "0-100",
                    "invalidation": "string",
                    "why_this_could_fail": "string",
                }
            ],
            "committee_summary": "string",
        },
    }


def write_debate(
    *,
    tickers: tuple[str, ...] | list[str] = (),
    from_scores: bool = False,
    top: int = 3,
    scores_path: Path | None = None,
    out_dir: Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    packet = build_debate_packet(
        tickers=tickers,
        from_scores=from_scores,
        top=top,
        scores_path=scores_path,
    )
    base = out_dir or ai_dir()
    packet_path = write_json(base / "debate_latest.json", packet)
    prompt = load_prompt("ai_debate.md")
    prompt_path = base / "debate_prompt.md"
    prompt_path.write_text(
        prompt
        + "\n\n---\n\n## Packet\n\n"
        + f"Read `{packet_path}` (schema `{SCHEMA}`) and reply in the response_schema JSON.\n",
        encoding="utf-8",
    )
    return packet, packet_path, prompt_path
