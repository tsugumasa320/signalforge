"""Hash-chained AI decision ledger (audit trail; no brokerage).

Inspired by open-source paper-fund ledgers: each event links to the previous
hash so silent rewrites are detectable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from signalforge.ai.packet import read_json, utc_now_iso, write_json
from signalforge.ai.paths import published_path

LEDGER_SCHEMA = "signalforge-ai-ledger/v1"
GENESIS_HASH = "0" * 64
PUBLISHED_NAME = "ai_ledger.json"


def ledger_path():
    return published_path(PUBLISHED_NAME)


def load_ledger() -> dict[str, Any]:
    raw = read_json(ledger_path())
    if isinstance(raw, dict) and isinstance(raw.get("events"), list):
        return raw
    return {"schema": LEDGER_SCHEMA, "events": []}


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_event(prev_hash: str, body: dict[str, Any]) -> str:
    material = f"{prev_hash}|{_canonical(body)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def last_hash(ledger: dict[str, Any] | None = None) -> str:
    events = (ledger or load_ledger()).get("events") or []
    if not events:
        return GENESIS_HASH
    return str(events[-1].get("hash") or GENESIS_HASH)


def append_event(
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Append one hash-linked event and persist. Returns the event."""
    ledger = load_ledger()
    events = list(ledger.get("events") or [])
    prev = last_hash(ledger)
    body = {
        "ts": utc_now_iso(),
        "kind": str(kind),
        "as_of": as_of,
        "payload": payload or {},
    }
    event = {
        **body,
        "prev_hash": prev,
        "hash": _hash_event(prev, body),
        "seq": len(events) + 1,
    }
    events.append(event)
    write_json(
        ledger_path(),
        {"schema": LEDGER_SCHEMA, "updated_at": utc_now_iso(), "events": events},
    )
    return event


def verify_ledger(ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return integrity check result for the chain."""
    events = list((ledger or load_ledger()).get("events") or [])
    prev = GENESIS_HASH
    for i, ev in enumerate(events):
        body = {
            "ts": ev.get("ts"),
            "kind": ev.get("kind"),
            "as_of": ev.get("as_of"),
            "payload": ev.get("payload") or {},
        }
        expected = _hash_event(prev, body)
        got = str(ev.get("hash") or "")
        if got != expected or str(ev.get("prev_hash") or "") != prev:
            return {
                "ok": False,
                "broken_at": i,
                "seq": ev.get("seq"),
                "expected_hash": expected,
                "got_hash": got,
                "n_events": len(events),
            }
        prev = got
    return {"ok": True, "n_events": len(events), "tip": prev if events else GENESIS_HASH}


def record_daily_run(
    *,
    as_of: str,
    adopted: list[str],
    score_n: int,
    debate_n: int,
    source: str = "rules/v1",
) -> dict[str, Any]:
    return append_event(
        "daily_run",
        {
            "source": source,
            "adopted": list(adopted),
            "score_n": score_n,
            "debate_n": debate_n,
            "roles": [
                "analyst_score",
                "brief_summarizer",
                "bull_researcher",
                "bear_researcher",
                "risk_officer",
                "human_approver",
            ],
        },
        as_of=as_of,
    )
