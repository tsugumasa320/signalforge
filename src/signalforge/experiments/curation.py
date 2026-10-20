"""Catalog curation: merge strategies with identical results, hide proxy / data-missing backtests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signalforge.config import data_dir

DUP_METRICS = ("expectancy_pct", "profit_factor", "win_rate", "total_trades")


def published_summary_path() -> Path:
    return data_dir() / "published" / "tse_strategy_summary.json"


def _metric_key(row: dict[str, Any]) -> tuple | None:
    vals = []
    for k in DUP_METRICS:
        v = row.get(k)
        if v is None or v != v:
            return None
        vals.append(round(float(v), 6))
    return tuple(vals)


def curate_strategy_rows(
    rows: list[dict[str, Any]],
    *,
    id_key: str = "strategy_id",
    hide_untrusted: bool = True,
    merge_duplicates: bool = True,
    preferred_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Returns (visible_rows, info). Duplicates = identical median metrics; the canonical row keeps
    `aliases`. preferred_ids (e.g. forward matrix) win canonical selection.
    """
    from signalforge.alt_data.trust import apply_trust_to_row

    preferred = preferred_ids or set()
    trusted: list[dict[str, Any]] = []
    hidden_untrusted: list[str] = []
    for r in rows:
        row = apply_trust_to_row(dict(r))
        if hide_untrusted and (row.get("metrics_trusted") is False or row.get("expectancy_pct") is None):
            hidden_untrusted.append(str(row.get(id_key) or ""))
            continue
        trusted.append(row)

    merged: list[str] = []
    if merge_duplicates:
        groups: dict[tuple, list[dict[str, Any]]] = {}
        singles: list[dict[str, Any]] = []
        for row in trusted:
            key = _metric_key(row)
            if key is None:
                singles.append(row)
            else:
                groups.setdefault(key, []).append(row)
        out: list[dict[str, Any]] = list(singles)
        for members in groups.values():
            members.sort(key=lambda m: (str(m.get(id_key)) not in preferred, str(m.get(id_key))))
            head = dict(members[0])
            aliases = [str(m.get(id_key)) for m in members[1:]]
            head["aliases"] = aliases
            merged.extend(aliases)
            out.append(head)
        trusted = out

    info = {
        "n_input": len(rows),
        "n_visible": len(trusted),
        "hidden_untrusted": sorted(i for i in hidden_untrusted if i),
        "merged_duplicates": sorted(merged),
    }
    return trusted, info


def build_published_summary() -> dict[str, Any]:
    """Slim, committed snapshot of the curated TSE ranking (Pages CI has no experiment data)."""
    from signalforge.experiments.portfolio_returns import load_portfolio_returns_cache
    from signalforge.experiments.scan import scan_campaign_progress
    from signalforge.paper.diversified_specs import DIVERSIFIED_PAPER_SIMULATIONS

    from signalforge.experiments.intraday_campaign import without_intraday

    scan = scan_campaign_progress(fast=True)
    forward = {s.strategy for s in DIVERSIFIED_PAPER_SIMULATIONS}
    daily = without_intraday(scan.get("complete") or [])
    rows, info = curate_strategy_rows(daily, preferred_ids=forward)
    cache = load_portfolio_returns_cache()
    port = cache.get("strategies") or {}
    keep = (
        "strategy_id",
        "style",
        "expectancy_pct",
        "profit_factor",
        "win_rate",
        "total_trades",
        "max_drawdown_pct",
        "n_tickers",
        "aliases",
    )
    slim: list[dict[str, Any]] = []
    for r in rows:
        item = {k: r.get(k) for k in keep}
        p = port.get(str(r.get("strategy_id"))) or {}
        if "total_return_pct" in p:
            item["portfolio"] = {
                k: p.get(k)
                for k in (
                    "total_return_pct",
                    "is_return_pct",
                    "oos_return_pct",
                    "max_drawdown_pct",
                    "accepted_trades",
                )
            }
        slim.append(item)
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "curation": info,
        "portfolio_params": cache.get("params") or {},
        "rows": slim,
    }
    path = published_summary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def load_published_summary() -> dict[str, Any]:
    path = published_summary_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
