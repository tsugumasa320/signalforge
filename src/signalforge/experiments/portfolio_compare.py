"""Compare 1-account entry rules with an early / late split and random tie-break distributions."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np

from signalforge.config import data_dir
from signalforge.lab.portfolio_sim import period_return_pct, simulate_diversified_portfolio, unpack_equity_daily
from signalforge.portfolio import entry_features as ef
from signalforge.portfolio.diversified import default_diversified_params, experiment_trade_pool

DEFAULT_OOS_START = "2024-01-01"
METRICS = ("total_return_pct", "is_return_pct", "oos_return_pct", "max_drawdown_pct", "accepted_trades")


def compare_path() -> Path:
    return data_dir() / "reports" / "experiments" / "portfolio_compare.json"


def load_portfolio_compare() -> dict[str, Any]:
    path = compare_path()
    if not path.exists():
        return {"rows": [], "params": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"rows": [], "params": {}}


def _one_run(pool, params: dict[str, Any], oos_start: str, **kw) -> dict[str, float]:
    sim = simulate_diversified_portfolio(pool, **params, **kw)
    eq = unpack_equity_daily(sim.get("equity_daily") or {})
    return {
        "total_return_pct": float(sim.get("total_return_pct") or 0.0),
        "is_return_pct": float(period_return_pct(eq, end=oos_start) or 0.0),
        "oos_return_pct": float(period_return_pct(eq, start=oos_start) or 0.0),
        "max_drawdown_pct": float(sim.get("max_drawdown_pct") or 0.0),
        "accepted_trades": float(sim.get("accepted_trades") or 0),
    }


def compare_portfolio_variants(
    strategy_ids: list[str],
    *,
    entry_priorities: list[str],
    regime_filters: list[str],
    min_turnovers: list[float] | None = None,
    min_breadths: list[float] | None = None,
    seeds: int = 10,
    oos_start: str = DEFAULT_OOS_START,
    initial_cash_jpy: float | None = None,
    max_positions: int = 5,
    position_pct: float = 0.2,
    progress_cb=None,
    write: bool = True,
) -> dict[str, Any]:
    """Each variant runs `seeds` random same-day orderings; median / p10 are reported."""
    params = default_diversified_params(
        initial_cash_jpy=initial_cash_jpy,
        max_positions=max_positions,
        position_pct=position_pct,
    )
    grid = list(
        itertools.product(entry_priorities, regime_filters, min_turnovers or [0.0], min_breadths or [0.0])
    )
    rows: list[dict[str, Any]] = []
    for sid in strategy_ids:
        try:
            pool = experiment_trade_pool(sid)
        except FileNotFoundError:
            continue
        if pool.empty:
            continue
        pool = ef.attach_regime(ef.attach_breadth(ef.attach_turnover(pool)))
        for prio, regime, tv, br in grid:
            runs = [
                _one_run(
                    pool,
                    params,
                    oos_start,
                    entry_priority=prio,
                    regime_filter=regime,
                    min_turnover_jpy=tv,
                    min_breadth_rank=br,
                    tie_break_seed=seed,
                )
                for seed in range(max(1, seeds))
            ]
            arr = {k: np.array([r[k] for r in runs]) for k in METRICS}
            row: dict[str, Any] = {
                "strategy_id": sid,
                "entry_priority": prio,
                "regime_filter": regime,
                "min_turnover_jpy": tv,
                "min_breadth_rank": br,
                "seeds": len(runs),
                **{k: float(np.median(v)) for k, v in arr.items()},
                "p10_return_pct": float(np.percentile(arr["total_return_pct"], 10)),
                "positive_share": float((arr["total_return_pct"] > 0).mean()),
            }
            rows.append(row)
            if progress_cb:
                progress_cb(row)
    doc = {"params": {**params, "oos_start": oos_start}, "rows": rows}
    if write:
        path = compare_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc
