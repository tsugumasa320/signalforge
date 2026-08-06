from __future__ import annotations

from typing import Any, Callable

import optuna

from signalforge.config import load_style_config
from signalforge.optimize.spaces import build_cfg_override, suggest_params
from signalforge.pipeline import run_backtest_pipeline


METRIC_KEYS = ("pf", "oos_pf", "sharpe", "oos_sharpe", "win_rate", "oos_win_rate")


def pick_metrics(result: dict[str, Any], metric: str, ml_filter: bool) -> dict[str, Any]:
    if metric.startswith("oos") or ml_filter:
        if metric in ("win_rate", "oos_win_rate"):
            from signalforge.report.dashboard_components import oos_metrics_from_trades

            return oos_metrics_from_trades(result["trades"], result["equity"])
        return result.get("metrics_oos", {})
    return result.get("metrics", {})


def score_from_metrics(metrics: dict[str, Any], metric: str) -> float:
    if metric in ("pf", "oos_pf"):
        return float(metrics.get("profit_factor", 0.0))
    if metric in ("sharpe", "oos_sharpe"):
        return float(metrics.get("sharpe", 0.0))
    if metric in ("win_rate", "oos_win_rate"):
        return float(metrics.get("win_rate", 0.0))
    return float(metrics.get("profit_factor", 0.0))


def make_objective(
    style: str,
    strategy: str,
    metric: str = "oos_pf",
    ml_filter: bool = False,
    min_trades: int = 5,
    max_drawdown_pct: float = 35.0,
    min_profit_factor: float = 1.0,
) -> Callable[[optuna.Trial], float]:
    base_cfg = load_style_config(style)
    use_oos = metric.startswith("oos") or ml_filter

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial, strategy)
        cfg_override = build_cfg_override(strategy, params, base_cfg)
        result = run_backtest_pipeline(
            style,
            strategy,
            ml_filter=ml_filter or use_oos,
            cfg_override=cfg_override,
        )
        metrics = pick_metrics(result, metric, ml_filter or use_oos)
        trades = int(metrics.get("total_trades", 0))
        if trades < min_trades:
            return -1.0

        pf = float(metrics.get("profit_factor", 0.0))
        if pf < min_profit_factor:
            return -1.0

        score = score_from_metrics(metrics, metric)
        dd = float(metrics.get("max_drawdown_pct", 0.0))
        if dd > max_drawdown_pct:
            score *= max(0.1, 1.0 - (dd - max_drawdown_pct) / 100.0)
        return score

    return objective
