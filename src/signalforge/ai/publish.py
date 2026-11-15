"""Publish AI responses into data/published/ for GitHub Pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from signalforge.ai.packet import write_json
from signalforge.ai.paths import ai_dir, published_path
from signalforge.config import ROOT

PUBLISHED_NAMES = {
    "brief": "ai_brief_response.json",
    "score": "ai_scores_response.json",
    "debate": "ai_debate_response.json",
}

EXAMPLE_NAMES = {
    "brief": "ai_brief_response.json",
    "score": "ai_score_response.json",
    "debate": "ai_debate_response.json",
}

LOCAL_NAMES = {
    "brief": "brief_response_latest.json",
    "score": "scores_response_latest.json",
    "debate": "debate_response_latest.json",
}


def published_response_path(kind: str) -> Path:
    name = PUBLISHED_NAMES[kind]
    return published_path(name)


def save_response(
    kind: str,
    payload: dict[str, Any],
    *,
    as_of: str | None = None,
) -> dict[str, Path]:
    """Write local data/ai copy and commit-friendly data/published copy."""
    base = ai_dir()
    outs: dict[str, Path] = {}
    if kind == "brief":
        outs["local"] = write_json(base / LOCAL_NAMES["brief"], payload)
    elif kind == "debate":
        outs["local"] = write_json(base / LOCAL_NAMES["debate"], payload)
    elif kind == "score":
        stamp = (as_of or payload.get("as_of") or "unknown").replace("-", "")
        write_json(base / f"scores_{stamp}.json", payload)
        outs["local"] = write_json(base / LOCAL_NAMES["score"], payload)
    else:
        raise ValueError(f"unknown kind: {kind}")
    outs["published"] = write_json(published_response_path(kind), payload)
    return outs


def load_response_for_pages(kind: str) -> dict[str, Any] | None:
    """Prefer published (Pages), then local ai/, then examples/."""
    from signalforge.ai.packet import read_json

    candidates = [
        published_response_path(kind),
        ai_dir() / LOCAL_NAMES[kind],
        ROOT / "examples" / EXAMPLE_NAMES[kind],
    ]
    for path in candidates:
        raw = read_json(path)
        if isinstance(raw, dict):
            return raw
    return None
