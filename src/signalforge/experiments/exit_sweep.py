"""Re-backtest strategies with alternative exit rules and score them under the 1-account entry rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from signalforge.compare.runner import run_cohort_backtests
from signalforge.config import data_dir
from signalforge.experiments.runner import resolve_campaign_backtest_capital
from signalforge.lab.portfolio_sim import (
    DEFAULT_ENTRY_RULES,
    period_return_pct,
    simulate_diversified_portfolio,
    unpack_equity_daily,
)
from signalforge.portfolio.diversified import (
    attach_entry_rule_features,
    default_diversified_params,
    entry_rule_kwargs,
    fill_missing_sectors,
    trades_pool_from_backtest_rows,
)
from signalforge.portfolio.entry_features import liquid_tickers

EXIT_VARIANTS: dict[str, dict[str, float]] = {
    "base_tp3_sl1.5_h15": {"atr_tp_multiple": 3.0, "atr_sl_multiple": 1.5, "max_hold_bars": 15},
    "quick_tp1.5_sl1.5_h5": {"atr_tp_multiple": 1.5, "atr_sl_multiple": 1.5, "max_hold_bars": 5},
    "tp2_sl1.5_h10": {"atr_tp_multiple": 2.0, "atr_sl_multiple": 1.5, "max_hold_bars": 10},
    "wide_tp2_sl3_h10": {"atr_tp_multiple": 2.0, "atr_sl_multiple": 3.0, "max_hold_bars": 10},
    "wide_tp3_sl3_h20": {"atr_tp_multiple": 3.0, "atr_sl_multiple": 3.0, "max_hold_bars": 20},
    "run_tp5_sl2_h25": {"atr_tp_multiple": 5.0, "atr_sl_multiple": 2.0, "max_hold_bars": 25},
}
OOS_START = "2024-01-01"


def sweep_path() -> Path:
    return data_dir() / "reports" / "experiments" / "exit_sweep.json"


def load_exit_sweep() -> dict[str, Any]:
    path = sweep_path()
    if not path.exists():
        return {"rows": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"rows": []}


def liquid_tse_tickers(min_median_turnover_jpy: float = 3e8) -> list[str]:
    return liquid_tickers(min_median_turnover_jpy, since="2020-01-01")


def _exit_override(base: dict[str, Any], exit_rules: dict[str, float]) -> dict[str, Any]:
    override = dict(base)
    override["rules"] = {"exit": {k: v for k, v in exit_rules.items() if k != "max_hold_bars"}}
    override["backtest"] = {**(base.get("backtest") or {}), "max_hold_bars": int(exit_rules["max_hold_bars"])}
    return override


def score_pool(pool: pd.DataFrame, *, seeds: int = 10, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = {**DEFAULT_ENTRY_RULES, **(rules or {})}
    params = default_diversified_params()
    pool = attach_entry_rule_features(fill_missing_sectors(pool), rules)
    kw = entry_rule_kwargs(rules)
    det = simulate_diversified_portfolio(pool, **params, **kw)
    det_eq = unpack_equity_daily(det["equity_daily"])
    rand = []
    for seed in range(seeds):
        s = simulate_diversified_portfolio(pool, **params, **{**kw, "entry_priority": "sector_random"}, tie_break_seed=seed)
        rand.append(float(s["total_return_pct"]))
    return {
        "n_trades_pool": int(len(pool)),
        "mean_pnl_pct": float(pool["pnl_pct"].mean()) if len(pool) else None,
        "total_return_pct": float(det["total_return_pct"]),
        "is_return_pct": period_return_pct(det_eq, end=OOS_START),
        "oos_return_pct": period_return_pct(det_eq, start=OOS_START),
        "max_drawdown_pct": float(det["max_drawdown_pct"]),
        "accepted_trades": int(det["accepted_trades"]),
        "random_median_return_pct": float(np.median(rand)) if rand else None,
        "random_p10_return_pct": float(np.percentile(rand, 10)) if rand else None,
    }


def run_exit_sweep(
    strategy_ids: list[str],
    *,
    variants: list[str] | None = None,
    tickers: list[str] | None = None,
    workers: int = 8,
    seeds: int = 10,
    progress_cb=None,
) -> dict[str, Any]:
    from signalforge.compare.runner import resolve_strategy_style
    from signalforge.config import load_web_catalog

    names = variants or list(EXIT_VARIANTS)
    universe = tickers or liquid_tse_tickers()
    _, cap_override = resolve_campaign_backtest_capital()
    catalog_by_id = {s["id"]: s for s in (load_web_catalog().get("strategies") or []) if s.get("id")}
    doc = load_exit_sweep()
    keep = [r for r in doc.get("rows") or [] if r.get("strategy_id") not in strategy_ids]
    rows: list[dict[str, Any]] = []
    for sid in strategy_ids:
        style = resolve_strategy_style(sid, catalog_by_id)
        for name in names:
            block = run_cohort_backtests(
                strategy_id=sid,
                style=style,
                tickers=universe,
                cost_model="japan",
                refresh=False,
                cfg_override=_exit_override(cap_override, EXIT_VARIANTS[name]),
                max_workers=workers,
            )
            pool = trades_pool_from_backtest_rows(block.get("tickers") or [])
            row = {
                "strategy_id": sid,
                "variant": name,
                **EXIT_VARIANTS[name],
                "n_tickers": len(universe),
                **score_pool(pool, seeds=seeds),
            }
            rows.append(row)
            if progress_cb:
                progress_cb(row)
            out = {"universe_size": len(universe), "oos_start": OOS_START, "rows": keep + rows}
            path = sweep_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"universe_size": len(universe), "rows": keep + rows}
