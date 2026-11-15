"""Daily AI trial pipeline: packets → rule responses → publish → adoption log/eval."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from signalforge.ai.adoption import append_adoptions_from_score, evaluate_adoptions
from signalforge.ai.approval import approval_summary, propose_from_score
from signalforge.ai.auto import (
    generate_brief_response,
    generate_debate_response,
    generate_score_response,
)
from signalforge.ai.brief import write_brief
from signalforge.ai.debate import write_debate
from signalforge.ai.ledger import record_daily_run, verify_ledger
from signalforge.ai.publish import save_response
from signalforge.ai.score import write_score


def run_daily(
    *,
    score_top: int = 20,
    debate_top: int = 3,
    max_adopt: int = 4,
    out_dir: Path | None = None,
    notify_discord: bool = True,
    fetch_news: bool = True,
) -> dict[str, Any]:
    brief_packet, brief_path, brief_prompt = write_brief(out_dir=out_dir)
    score_packet, score_path, score_prompt = write_score(
        top=score_top,
        out_dir=out_dir,
        fetch_news=fetch_news,
    )
    score_resp = generate_score_response(score_packet, max_adopt=max_adopt)

    # attach prices from candidates for adoption log
    price_map = {str(c.get("ticker")): c.get("price") for c in (score_packet.get("candidates") or [])}
    for s in score_resp.get("scores") or []:
        t = str(s.get("ticker") or "")
        if t and s.get("price") is None:
            s["price"] = price_map.get(t)

    brief_resp = generate_brief_response(brief_packet, score_resp)
    save_response("score", score_resp, as_of=str(score_resp.get("as_of") or ""))
    save_response("brief", brief_resp)

    debate_packet, debate_path, debate_prompt = write_debate(
        from_scores=True,
        top=debate_top,
        out_dir=out_dir,
    )
    debate_resp = generate_debate_response(debate_packet)
    save_response("debate", debate_resp)

    as_of = str(score_resp.get("as_of") or "")
    adopted = list(score_resp.get("adopted") or [])
    log = append_adoptions_from_score(score_resp, source="rules/v1")
    approvals = propose_from_score(score_resp, source="rules/v1")
    record_daily_run(
        as_of=as_of,
        adopted=[str(t) for t in adopted],
        score_n=len(score_resp.get("scores") or []),
        debate_n=len(debate_resp.get("debates") or []),
        source="rules/v1",
    )
    ledger_check = verify_ledger()
    eval_payload = evaluate_adoptions()

    discord: dict[str, Any] | None = None
    if notify_discord:
        from signalforge.ai.discord_notify import notify_daily

        try:
            discord = notify_daily(
                as_of=as_of,
                adopted=adopted,
                brief_resp=brief_resp,
                eval_summary=eval_payload.get("summary") or {},
                pending_count=int(approvals.get("pending_count") or 0),
            )
        except Exception as exc:  # noqa: BLE001 — CI should not fail the whole daily job
            discord = {"ok": False, "skipped": False, "error": str(exc)}

    return {
        "as_of": score_resp.get("as_of"),
        "adopted": score_resp.get("adopted"),
        "brief_resp": brief_resp,
        "brief_path": str(brief_path),
        "score_path": str(score_path),
        "debate_path": str(debate_path),
        "brief_prompt": str(brief_prompt),
        "score_prompt": str(score_prompt),
        "debate_prompt": str(debate_prompt),
        "adoption_entries": len(log.get("entries") or []),
        "approvals_created": approvals.get("created") or [],
        "approvals_summary": approval_summary(),
        "ledger_ok": bool(ledger_check.get("ok")),
        "ledger_events": ledger_check.get("n_events"),
        "eval_summary": eval_payload.get("summary"),
        "discord": discord,
    }
