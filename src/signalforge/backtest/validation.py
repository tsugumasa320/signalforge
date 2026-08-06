from __future__ import annotations

from typing import Any

import pandas as pd


def check_oos_degradation(
    train_metrics: dict[str, Any],
    test_metrics: dict[str, Any],
    pf_threshold: float = 0.7,
) -> dict[str, Any]:
    """Flag if OOS performance degraded significantly vs train."""
    train_pf = train_metrics.get("profit_factor", 0)
    test_pf = test_metrics.get("profit_factor", 0)
    degraded = False
    if train_pf > 0:
        ratio = test_pf / train_pf if train_pf else 0
        degraded = ratio < pf_threshold
    return {
        "train_pf": train_pf,
        "test_pf": test_pf,
        "degraded": degraded,
        "message": "OOS degraded — consider rejecting strategy" if degraded else "OOS acceptable",
    }


def permutation_test(returns: pd.Series, n_perms: int = 100) -> dict[str, Any]:
    """Simple permutation test on trade returns."""
    if len(returns) < 5:
        return {"p_value": 1.0, "observed_mean": 0.0}
    observed = returns.mean()
    count = 0
    rng = pd.Series(range(n_perms))
    for _ in rng:
        shuffled = returns.sample(frac=1, replace=False).values
        if shuffled.mean() >= observed:
            count += 1
    return {
        "p_value": count / n_perms,
        "observed_mean": float(observed),
    }
