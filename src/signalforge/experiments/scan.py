"""Filesystem scan for TSE experiment campaign progress (CLI + dashboard)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signalforge.config import data_dir, load_web_catalog
from signalforge.experiments.checkpoint_meta import read_checkpoint_progress


def _strategies_dir() -> Path:
    return data_dir() / "reports" / "experiments" / "strategies"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def planned_strategy_count() -> int:
    return sum(
        1
        for s in load_web_catalog().get("strategies", [])
        if s.get("implemented") and s.get("id")
    )


def scan_campaign_progress(*, strategies_dir: Path | None = None) -> dict[str, Any]:
    d = strategies_dir or _strategies_dir()
    complete: list[dict[str, Any]] = []
    in_progress: list[dict[str, Any]] = []
    total_planned = planned_strategy_count()

    if not d.is_dir():
        return {
            "complete": complete,
            "in_progress": in_progress,
            "total_planned": total_planned,
            "n_tickers_pool": None,
            "manifest": {},
        }

    for path in sorted(d.glob("*.json")):
        if path.name.endswith(".tickers.json"):
            continue
        if path.name.endswith(".checkpoint.json"):
            sid = path.name.replace(".checkpoint.json", "")
            prog = read_checkpoint_progress(path)
            in_progress.append(
                {
                    "strategy_id": sid,
                    "n_done": prog["n_tickers_done"],
                    "n_target": prog["n_tickers_target"],
                    "source": "checkpoint",
                    "mtime": path.stat().st_mtime,
                }
            )
            continue
        if path.name.endswith(".checkpoint.tickers.json"):
            continue
        doc = _load_json(path)
        if not doc or doc.get("error"):
            continue
        sid = str(doc.get("strategy_id") or path.stem)
        target = int(doc.get("n_tickers_target") or 0)
        done = int(doc.get("n_tickers_done") or 0)
        if doc.get("complete") and target > 0 and done >= target:
            u = doc.get("universe") or {}
            complete.append(
                {
                    "strategy_id": sid,
                    "style": doc.get("style"),
                    "median_pf": u.get("median_profit_factor"),
                    "mean_pf": u.get("mean_profit_factor"),
                    "n_tickers": u.get("n_tickers"),
                    "pct_pf_gt_1": u.get("pct_pf_above_1"),
                    "mtime": path.stat().st_mtime,
                }
            )
        elif done > 0 and not doc.get("complete"):
            in_progress.append(
                {
                    "strategy_id": sid,
                    "n_done": done,
                    "n_target": target or done,
                    "source": "partial",
                    "mtime": path.stat().st_mtime,
                }
            )

    complete.sort(key=lambda x: float(x.get("median_pf") or 0), reverse=True)
    # Prefer checkpoint row when both exist for same strategy
    by_sid: dict[str, dict[str, Any]] = {}
    for row in in_progress:
        sid = row["strategy_id"]
        prev = by_sid.get(sid)
        if prev is None or row.get("n_done", 0) >= prev.get("n_done", 0):
            by_sid[sid] = row
    in_progress = sorted(by_sid.values(), key=lambda r: r.get("strategy_id", ""))
    if in_progress:
        latest_mtime = max(float(r.get("mtime") or 0) for r in in_progress)
        for row in in_progress:
            row["active"] = float(row.get("mtime") or 0) >= latest_mtime - 1.0

    manifest_path = data_dir() / "reports" / "experiments" / "manifest.json"
    manifest = _load_json(manifest_path) or {}
    targets = [int(r.get("n_target") or 0) for r in in_progress if int(r.get("n_target") or 0) > 0]
    man_n = int(manifest.get("n_tickers") or 0)
    if targets:
        pool = max(targets)
    elif man_n > 50:
        pool = man_n
    elif complete:
        pool = complete[0].get("n_tickers")
    else:
        pool = man_n or None

    return {
        "complete": complete,
        "in_progress": in_progress,
        "total_planned": total_planned,
        "n_tickers_pool": pool,
        "manifest": manifest,
    }
