"""Discord webhook notifications for AI daily brief."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

PAGES_AI_URL = "https://tsugumasa320.github.io/signalforge/ai/"


def webhook_url_from_env() -> str | None:
    raw = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip()
    return raw or None


def build_daily_message(
    *,
    as_of: str | None,
    adopted: list[str] | None,
    brief_resp: dict[str, Any] | None,
    eval_summary: dict[str, Any] | None = None,
    eval_summary_approved: dict[str, Any] | None = None,
    pending_count: int | None = None,
) -> str:
    adopted = [str(t) for t in (adopted or []) if t]
    brief = brief_resp or {}
    lines = [
        "**SignalForge AI daily**",
        f"基準日: `{as_of or '—'}`",
        f"ADOPT提案: {', '.join(f'`{t}`' for t in adopted) if adopted else '—'}",
    ]
    if pending_count is not None:
        lines.append(f"承認待ち: {pending_count}（`ai pending` / `ai approve`）")
    regime = (brief_resp or {}).get("market_regime") if isinstance(brief_resp, dict) else None
    if isinstance(regime, dict) and regime.get("overall"):
        lines.append(
            f"地合い: `{regime.get('overall')}` "
            f"(JP `{regime.get('jp')}` / US `{regime.get('us')}`)"
        )
    take = brief.get("market_take")
    if take:
        lines.append(f"要約: {take}")

    actions = brief.get("actions_for_human") or []
    if actions:
        lines.append("人がやること:")
        for a in actions[:5]:
            lines.append(f"- {a}")

    skip = brief.get("skip_today") or []
    if skip:
        lines.append("今日やらないこと:")
        for s in skip[:4]:
            lines.append(f"- {s}")

    summary = eval_summary or {}
    mean5 = summary.get("mean_ret_5d")
    n5 = summary.get("n_eval_5d")
    if n5:
        mean_s = f"{float(mean5):+.1%}" if mean5 is not None else "—"
        lines.append(f"提案 5日: n={n5} mean={mean_s}")

    approved = eval_summary_approved or {}
    n_paper = approved.get("n_paper_intents") or approved.get("n_adopted_rows")
    n5a = approved.get("n_eval_5d")
    if n_paper:
        mean_a = approved.get("mean_ret_5d")
        mean_as = f"{float(mean_a):+.1%}" if mean_a is not None and n5a else "pending"
        lines.append(f"Paper(approved) 5日: intents={n_paper} n={n5a or 0} mean={mean_as}")

    lines.append(f"詳細: {PAGES_AI_URL}")
    text = "\n".join(lines)
    # Discord content hard limit ~2000
    if len(text) > 1900:
        text = text[:1890] + "…"
    return text


def post_webhook(url: str, content: str, *, timeout: float = 15.0) -> dict[str, Any]:
    body = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "SignalForge/ai-daily"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": getattr(resp, "status", 204), "body": raw}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord webhook HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Discord webhook failed: {exc}") from exc


def notify_daily(
    *,
    as_of: str | None,
    adopted: list[str] | None,
    brief_resp: dict[str, Any] | None,
    eval_summary: dict[str, Any] | None = None,
    eval_summary_approved: dict[str, Any] | None = None,
    pending_count: int | None = None,
    webhook_url: str | None = None,
) -> dict[str, Any]:
    """Post daily summary. Skips when webhook URL is missing."""
    url = (webhook_url or webhook_url_from_env() or "").strip()
    if not url:
        return {"ok": False, "skipped": True, "reason": "DISCORD_WEBHOOK_URL unset"}
    content = build_daily_message(
        as_of=as_of,
        adopted=adopted,
        brief_resp=brief_resp,
        eval_summary=eval_summary,
        eval_summary_approved=eval_summary_approved,
        pending_count=pending_count,
    )
    result = post_webhook(url, content)
    result["skipped"] = False
    result["content_preview"] = content[:200]
    return result
