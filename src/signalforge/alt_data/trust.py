"""When to show experiment metrics vs blank (proxy / missing alt-data)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from signalforge.alt_data.deps import data_deps_for_strategy
from signalforge.alt_data.credit_balance import credit_dir
from signalforge.alt_data.earnings import earnings_path
from signalforge.alt_data.paths import sector_index_meta_path, sector_indices_dir
from signalforge.alt_data.sector_index import tickers_by_sector
from signalforge.config import load_implementation_map
from signalforge.universe.tse_listing import list_tse_tickers

METRIC_FIELDS = (
    "expectancy_pct",
    "profit_factor",
    "win_rate",
    "total_trades",
    "max_drawdown_pct",
)


@lru_cache(maxsize=1)
def _coverage_snapshot() -> dict[str, Any]:
    tickers = list_tse_tickers()
    n = max(len(tickers), 1)
    sectors = tickers_by_sector()
    built = 0
    meta_path = sector_index_meta_path()
    if meta_path.exists():
        import json

        try:
            built = len(json.loads(meta_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            built = len(list(sector_indices_dir().glob("*.parquet")))
    earn = sum(1 for t in tickers if earnings_path(t).exists())
    credit = len(list(credit_dir().glob("*.json")))
    return {
        "n_tickers": n,
        "sector_groups": len(sectors),
        "sector_indices_built": built,
        "earnings_files": earn,
        "credit_files": credit,
    }


def _deps_ready(deps: list[str]) -> tuple[bool, str]:
    cov = _coverage_snapshot()
    n = cov["n_tickers"]
    if "sector_index" in deps:
        if cov["sector_indices_built"] < cov["sector_groups"]:
            return False, "業種指数未準備"
    if "earnings" in deps:
        if cov["earnings_files"] < max(50, int(n * 0.25)):
            return False, "決算日データ不足"
    if "credit_balance" in deps:
        if cov["credit_files"] < max(50, int(n * 0.25)):
            return False, "信用残未取得"
    return True, ""


def strategy_trust(strategy_id: str) -> dict[str, Any]:
    impl = load_implementation_map().get("strategies", {}).get(strategy_id) or {}
    approx = (impl.get("approximation") or "").strip()
    deps = data_deps_for_strategy(strategy_id)

    if approx:
        return {
            "display_metrics": False,
            "metrics_note": "代理BT（データ不足）",
            "detail": approx,
        }

    if deps:
        ok, msg = _deps_ready(deps)
        if not ok:
            return {
                "display_metrics": False,
                "metrics_note": msg,
                "detail": f"data_deps={deps}",
            }

    return {"display_metrics": True, "metrics_note": "", "detail": ""}


def apply_trust_to_row(row: dict[str, Any]) -> dict[str, Any]:
    sid = str(row.get("strategy_id") or "")
    trust = strategy_trust(sid)
    out = dict(row)
    out["metrics_trusted"] = trust["display_metrics"]
    out["metrics_note"] = trust["metrics_note"] or None
    if not trust["display_metrics"]:
        for k in METRIC_FIELDS:
            if k in out:
                out[k] = None
    return out


def strategies_ready_for_rerun() -> list[str]:
    """Completed strategies that use real alt-data (no approximation, deps ready)."""
    impl = load_implementation_map().get("strategies") or {}
    out: list[str] = []
    for sid in impl:
        spec = impl[sid]
        if spec.get("approximation"):
            continue
        deps = data_deps_for_strategy(sid)
        if not deps:
            continue
        ok, _ = _deps_ready(deps)
        if ok:
            out.append(sid)
    return sorted(out)
