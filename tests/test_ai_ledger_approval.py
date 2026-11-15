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
            {"ticker": "7203.T", "name": "トヨタ", "total": 88, "decision": "ADOPT", "price": 3000},
            {"ticker": "6758.T", "name": "ソニー", "total": 84, "decision": "ADOPT", "price": 4000},
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


def test_evaluate_splits_approved_paper_intent(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd

    from signalforge.ai.adoption import append_adoptions_from_score, evaluate_adoptions

    score = {
        "as_of": "2026-11-13",
        "adopted": ["7203.T", "6758.T"],
        "scores": [
            {"ticker": "7203.T", "name": "トヨタ", "total": 88, "decision": "ADOPT", "price": 3000.0},
            {"ticker": "6758.T", "name": "ソニー", "total": 84, "decision": "ADOPT", "price": 4000.0},
        ],
    }
    propose_from_score(score)
    resolve("7203.T", status="approved")
    resolve("6758.T", status="rejected")
    append_adoptions_from_score(score)

    idx = pd.date_range("2026-11-13", periods=30, freq="B", tz="UTC")
    for ticker, start in (("7203.T", 3000), ("6758.T", 4000)):
        px = pd.DataFrame(
            {
                "open": start,
                "high": start + 10,
                "low": start - 10,
                "close": [start + i * 10 for i in range(30)],
                "volume": 1e6,
            },
            index=idx,
        )
        px.to_pickle(data_dir / f"{ticker}_1d.pkl")

    ev = evaluate_adoptions()
    assert ev["summary"]["n_adopted_rows"] == 2
    assert ev["summary_approved"]["n_paper_intents"] == 1
    assert ev["summary_approved"]["n_eval_5d"] == 1
    gates = {r["ticker"]: r["gate"] for r in ev["rows"]}
    assert gates["7203.T"] == "approved"
    assert gates["6758.T"] == "rejected"
    assert {r["ticker"] for r in ev["rows"] if r["paper_intent"]} == {"7203.T"}
