"""Hash ledger + human approval gate for AI ADOPT proposals."""

from __future__ import annotations

from pathlib import Path

import pytest

from signalforge.ai.approval import list_pending, load_approvals, propose_from_score, resolve
from signalforge.ai.ledger import append_event, load_ledger, verify_ledger


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    (data / "published").mkdir(parents=True)
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(data))
    return data


def test_ledger_hash_chain(data_dir: Path) -> None:
    e1 = append_event("daily_run", {"adopted": ["7203.T"]}, as_of="2026-11-13")
    e2 = append_event("adopt_proposed", {"ticker": "7203.T"}, as_of="2026-11-13")
    assert e1["prev_hash"] == "0" * 64
    assert e2["prev_hash"] == e1["hash"]
    assert verify_ledger()["ok"] is True
    ledger = load_ledger()
    ledger["events"][0]["payload"]["tamper"] = True
    assert verify_ledger(ledger)["ok"] is False


def test_approval_propose_and_resolve(data_dir: Path) -> None:
    score = {
        "as_of": "2026-11-13",
        "adopted": ["7203.T", "6758.T"],
        "scores": [
            {"ticker": "7203.T", "name": "トヨタ", "total": 88, "decision": "ADOPT"},
            {"ticker": "6758.T", "name": "ソニー", "total": 84, "decision": "ADOPT"},
        ],
    }
    out = propose_from_score(score, source="rules/v1")
    assert set(out["created"]) == {"7203.T", "6758.T"}
    assert len(list_pending()) == 2
    # idempotent
    out2 = propose_from_score(score)
    assert out2["created"] == []
    approved = resolve("7203.T", status="approved", note="ok")
    assert approved["status"] == "approved"
    rejected = resolve("6758.T", status="rejected", note="過熱")
    assert rejected["status"] == "rejected"
    assert list_pending() == []
    items = load_approvals()["items"]
    assert {i["ticker"]: i["status"] for i in items} == {
        "7203.T": "approved",
        "6758.T": "rejected",
    }
    assert verify_ledger()["ok"] is True
    kinds = [e["kind"] for e in load_ledger()["events"]]
    assert "adopt_proposed" in kinds
    assert "adopt_approved" in kinds
    assert "adopt_rejected" in kinds
