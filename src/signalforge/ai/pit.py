"""Point-in-time visibility gates for AI packets (KabuForge-inspired, thin).

Decision time is ``as_of`` (signal / ranking day). Content whose disclosed
``available_at`` is after that day must not influence scores. This is a
visibility check only — not a full historical PIT certification.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

PIT_SCHEMA = "signalforge-ai-pit/v1"


def parse_day(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _news_day(item: dict[str, Any]) -> date | None:
    return parse_day(item.get("published_at") or item.get("pubDate") or item.get("date"))


def annotate_pit(row: dict[str, Any], *, as_of: str | date | None) -> dict[str, Any]:
    """Attach pit_* fields and drop post-as_of surprise / news from the row."""
    out = dict(row)
    decision = parse_day(as_of)
    issues: list[str] = []
    available_dates: list[date] = []

    if decision is None:
        out["pit_ok"] = True
        out["pit_status"] = "no_as_of"
        out["pit_available_at"] = None
        out["pit_decision_as_of"] = None
        out["pit_issues"] = ["as_of missing — PIT gate skipped"]
        return out

    surprise = out.get("surprise") if isinstance(out.get("surprise"), dict) else None
    if surprise:
        disc = parse_day(surprise.get("disc_date"))
        if disc is None:
            issues.append("surprise_missing_disc_date")
            out.pop("surprise", None)
        elif disc > decision:
            issues.append(f"surprise_after_as_of:{disc.isoformat()}")
            out.pop("surprise", None)
        else:
            available_dates.append(disc)

    news = [n for n in (out.get("news") or []) if isinstance(n, dict)]
    kept_news: list[dict[str, Any]] = []
    for n in news:
        nd = _news_day(n)
        if nd is None:
            # Unknown publish time: keep but flag (visibility unverified).
            issues.append("news_missing_published_at")
            kept_news.append(n)
            continue
        if nd > decision:
            issues.append(f"news_after_as_of:{nd.isoformat()}")
            continue
        available_dates.append(nd)
        kept_news.append(n)
    if kept_news:
        out["news"] = kept_news
        from signalforge.ai.content import news_sentiment

        out["news_sentiment"] = news_sentiment([str(n.get("title") or "") for n in kept_news])
    else:
        out.pop("news", None)
        out.pop("news_sentiment", None)

    has_s = isinstance(out.get("surprise"), dict)
    has_n = bool(out.get("news"))
    if has_s and has_n:
        out["content_data"] = "both"
    elif has_s:
        out["content_data"] = "surprise"
    elif has_n:
        out["content_data"] = "news"
    else:
        out["content_data"] = "missing"

    # Forward-looking earnings_next is public schedule → OK (not a leak).
    # earnings_last is historical → available after that day.
    last = parse_day(out.get("earnings_last"))
    if last is not None and last <= decision:
        available_dates.append(last)

    available_at = max(available_dates).isoformat() if available_dates else None
    # Hard fail only when we detected post-as_of content that was stripped.
    hard = [i for i in issues if i.startswith("surprise_after_as_of") or i.startswith("news_after_as_of")]
    pit_ok = not hard
    out["pit_ok"] = pit_ok
    out["pit_status"] = "ok" if pit_ok and not issues else ("stripped" if hard else "warn")
    out["pit_available_at"] = available_at
    out["pit_decision_as_of"] = decision.isoformat()
    out["pit_issues"] = issues
    return out


def annotate_pit_rows(
    rows: list[dict[str, Any]],
    *,
    as_of: str | date | None,
) -> list[dict[str, Any]]:
    return [annotate_pit(r, as_of=as_of) for r in rows]


def pit_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    n = len(rows)
    return {
        "n": n,
        "ok": sum(1 for r in rows if r.get("pit_ok") is True),
        "stripped": sum(1 for r in rows if r.get("pit_status") == "stripped"),
        "warn": sum(1 for r in rows if r.get("pit_status") == "warn"),
        "schema": PIT_SCHEMA,
    }
