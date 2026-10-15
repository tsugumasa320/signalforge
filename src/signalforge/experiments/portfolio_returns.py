"""Cache 1-account portfolio sim returns for dashboard ranking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signalforge.config import data_dir
from signalforge.portfolio.diversified import simulate_from_experiment_strategy


def cache_path() -> Path:
    return data_dir() / "reports" / "experiments" / "portfolio_returns.json"


def load_portfolio_returns_cache() -> dict[str, Any]:
    path = cache_path()
    if not path.exists():
        return {"strategies": {}, "params": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"strategies": {}, "params": {}}


def build_portfolio_returns_cache(
    strategy_ids: list[str],
    *,
    initial_cash_jpy: float | None = None,
    max_positions: int = 5,
    position_pct: float = 0.2,
    entry_priority: str = "sector_liquidity",
) -> dict[str, Any]:
    from signalforge.portfolio.diversified import default_diversified_params

    params = default_diversified_params(
        initial_cash_jpy=initial_cash_jpy,
        max_positions=max_positions,
        position_pct=position_pct,
    )
    strategies: dict[str, Any] = {}
    for sid in strategy_ids:
        try:
            out = simulate_from_experiment_strategy(
                sid,
                initial_cash_jpy=params["initial_capital"],
                max_positions=max_positions,
                position_pct=position_pct,
                entry_after=None,
                entry_priority=entry_priority,
            )
            strategies[sid] = {
                "total_return_pct": out.get("total_return_pct"),
                "final_equity": out.get("final_equity"),
                "accepted_trades": out.get("accepted_trades"),
                "skipped_overlap": out.get("skipped_overlap"),
            }
        except FileNotFoundError:
            continue
        except Exception as exc:
            strategies[sid] = {"error": str(exc)}
    doc = {
        "params": {**params, "entry_priority": entry_priority, "max_positions": max_positions, "position_pct": position_pct},
        "strategies": strategies,
    }
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc
