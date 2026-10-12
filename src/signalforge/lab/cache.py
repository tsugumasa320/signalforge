"""Incremental study cache (Izanami 差分検証 approximation)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from signalforge.config import data_dir


def _cache_dir() -> Path:
    p = data_dir() / "lab_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def fingerprint(rule_id: str, tickers: list[str], cfg: dict[str, Any]) -> str:
    raw = json.dumps(
        {"rule": rule_id, "tickers": sorted(tickers), "cfg": cfg},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def load_study(fp: str) -> dict[str, Any] | None:
    path = _cache_dir() / f"{fp}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_study(fp: str, payload: dict[str, Any]) -> Path:
    path = _cache_dir() / f"{fp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def merge_ticker_results(cached: dict[str, Any], fresh_by_ticker: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace per-ticker blocks; keep other tickers from cache."""
    old = {b["ticker"]: b for b in cached.get("by_ticker", []) if b.get("ticker")}
    for block in fresh_by_ticker:
        if block.get("ticker"):
            old[block["ticker"]] = block
    merged = dict(cached)
    merged["by_ticker"] = list(old.values())
    return merged
