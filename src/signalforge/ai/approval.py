"""Human approval gate for AI ADOPT proposals (no brokerage).

ai-hedge-fund style: system proposes → human approves/rejects before treating
as an intentional paper intent. Forward eval tracks all proposals; approved
rows get a separate paper-intent summary.
"""

from __future__ import annotations

from typing import Any

from signalforge.ai.ledger import append_event
from signalforge.ai.packet import read_json, utc_now_iso, write_json
from signalforge.ai.paths import published_path

APPROVAL_SCHEMA = "signalforge-ai-approvals/v1"
PUBLISHED_NAME = "ai_approvals.json"
STATUSES = ("pending", "approved", "rejected")


def approvals_path():
    return published_path(PUBLISHED_NAME)


def load_approvals() -> dict[str, Any]:
    raw = read_json(approvals_path())
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return raw
    return {"schema": APPROVAL_SCHEMA, "items": []}


def _save(items: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"schema": APPROVAL_SCHEMA, "updated_at": utc_now_iso(), "items": items}
    write_json(approvals_path(), payload)
    return payload


def item_id(as_of: str, ticker: str) -> str:
    return f"{as_of}:{ticker}"


def propose_from_score(
    score_resp: dict[str, Any],
    *,
    source: str = "rules/v1",
) -> dict[str, Any]:
    """Create pending approval rows for ADOPT tickers (idempotent per as_of+ticker)."""
    as_of = str(score_resp.get("as_of") or "")
    if not as_of:
        raise ValueError("score response needs as_of")
    scores = {str(s.get("ticker")): s for s in (score_resp.get("scores") or []) if s.get("ticker")}
    adopted = [str(t) for t in (score_resp.get("adopted") or []) if t]
    if not adopted:
        adopted = [
            str(s["ticker"])
            for s in (score_resp.get("scores") or [])
            if s.get("decision") == "ADOPT" and s.get("ticker")
        ]

    store = load_approvals()
    items = list(store.get("items") or [])
    by_id = {str(i.get("id")): i for i in items}
    created: list[str] = []
    for t in adopted:
        iid = item_id(as_of, t)
        if iid in by_id:
            continue
        s = scores.get(t) or {}
        row = {
            "id": iid,
            "as_of": as_of,
            "ticker": t,
            "name": s.get("name"),
            "total": s.get("total"),
            "price": s.get("price"),
            "source": source,
            "status": "pending",
            "proposed_at": utc_now_iso(),
            "resolved_at": None,
            "note": "",
        }
        items.append(row)
        by_id[iid] = row
        created.append(t)
        append_event(
            "adopt_proposed",
            {"ticker": t, "name": s.get("name"), "total": s.get("total"), "source": source},
            as_of=as_of,
        )

    payload = _save(items)
    payload["created"] = created
    payload["pending_count"] = sum(1 for i in items if i.get("status") == "pending")
    return payload


def list_pending(*, as_of: str | None = None) -> list[dict[str, Any]]:
    items = load_approvals().get("items") or []
    out = [i for i in items if i.get("status") == "pending"]
    if as_of:
        out = [i for i in out if str(i.get("as_of")) == as_of]
    return out


def resolve(
    ticker: str,
    *,
    status: str,
    as_of: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Approve or reject a pending ADOPT. status must be approved|rejected."""
    status = str(status).lower().strip()
    if status not in ("approved", "rejected"):
        raise ValueError("status must be approved or rejected")
    ticker = str(ticker).strip()
    store = load_approvals()
    items = list(store.get("items") or [])
    target: dict[str, Any] | None = None
    for i in items:
        if str(i.get("ticker")) != ticker:
            continue
        if as_of and str(i.get("as_of")) != as_of:
            continue
        if i.get("status") != "pending":
            continue
        target = i
        break
    if target is None:
        # Prefer latest pending for ticker when as_of omitted
        if as_of is None:
            for i in reversed(items):
                if str(i.get("ticker")) == ticker and i.get("status") == "pending":
                    target = i
                    break
    if target is None:
        raise LookupError(f"pending approval not found for {ticker}" + (f" as_of={as_of}" if as_of else ""))

    target["status"] = status
    target["resolved_at"] = utc_now_iso()
    target["note"] = note or ""
    _save(items)
    append_event(
        f"adopt_{status}",
        {
            "ticker": target.get("ticker"),
            "name": target.get("name"),
            "total": target.get("total"),
            "note": note or "",
            "id": target.get("id"),
        },
        as_of=str(target.get("as_of") or ""),
    )
    return target


def approval_summary() -> dict[str, int]:
    items = load_approvals().get("items") or []
    counts = {"pending": 0, "approved": 0, "rejected": 0, "total": len(items)}
    for i in items:
        st = str(i.get("status") or "")
        if st in counts:
            counts[st] += 1
    return counts


def approval_status_map() -> dict[str, str]:
    """Map `as_of:ticker` → pending|approved|rejected."""
    out: dict[str, str] = {}
    for i in load_approvals().get("items") or []:
        as_of = str(i.get("as_of") or "")
        ticker = str(i.get("ticker") or "")
        st = str(i.get("status") or "")
        if as_of and ticker and st:
            out[item_id(as_of, ticker)] = st
    return out


def list_approved(*, as_of: str | None = None) -> list[dict[str, Any]]:
    items = load_approvals().get("items") or []
    out = [i for i in items if i.get("status") == "approved"]
    if as_of:
        out = [i for i in out if str(i.get("as_of")) == as_of]
    return out
