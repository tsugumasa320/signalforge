"""Flat cohort breakdown (universe / segment / sector) per strategy for matrix tables."""

from __future__ import annotations

from typing import Any

from signalforge.experiments.storage import load_strategy_header
from signalforge.experiments.ticker_cohort import TSE_SEGMENT_LABELS, ranking_row_from_aggregate


def _aggregate_to_row(
    base: dict[str, Any],
    cohort_kind: str,
    cohort_key: str,
    cohort_label: str,
    agg: dict[str, Any],
) -> dict[str, Any]:
    n_ok = int(agg.get("n_ok") or agg.get("n_tickers") or 0)
    n_valid = n_ok
    row = ranking_row_from_aggregate(base, agg, n_valid=n_valid, n_ok=n_ok)
    row["cohort_kind"] = cohort_kind
    row["cohort_key"] = cohort_key
    row["cohort_label"] = cohort_label
    row["median_return_pct"] = agg.get("median_total_return_pct")
    return row


def breakdown_rows_for_strategy(strategy_id: str, doc: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    doc = doc if doc is not None else load_strategy_header(strategy_id)
    if not doc or not doc.get("complete"):
        return []
    base = {
        "strategy_id": strategy_id,
        "style": doc.get("style") or "swing",
    }
    rows: list[dict[str, Any]] = []
    u = doc.get("universe")
    if isinstance(u, dict) and u.get("n_tickers"):
        rows.append(_aggregate_to_row(base, "universe", "all", "全体", u))
    for seg, agg in (doc.get("by_segment") or {}).items():
        if not isinstance(agg, dict):
            continue
        label = TSE_SEGMENT_LABELS.get(str(seg), str(seg))
        rows.append(_aggregate_to_row(base, "segment", str(seg), label, agg))
    for sec, agg in (doc.get("by_sector") or {}).items():
        if not isinstance(agg, dict) or not sec:
            continue
        rows.append(_aggregate_to_row(base, "sector", str(sec), str(sec), agg))
    return rows


def build_cohort_matrix(complete: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (strategy × cohort slice) from stored aggregates."""
    out: list[dict[str, Any]] = []
    trusted_map = {str(r.get("strategy_id")): r for r in complete if r.get("strategy_id")}
    for sid, scan_row in trusted_map.items():
        doc = load_strategy_header(sid)
        for row in breakdown_rows_for_strategy(sid, doc):
            row["metrics_trusted"] = scan_row.get("metrics_trusted")
            row["metrics_note"] = scan_row.get("metrics_note")
            if scan_row.get("metrics_trusted") is False:
                for key in (
                    "expectancy_pct",
                    "profit_factor",
                    "win_rate",
                    "total_trades",
                    "max_drawdown_pct",
                    "median_return_pct",
                ):
                    row[key] = None
            out.append(row)
    return out
