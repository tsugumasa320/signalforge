from __future__ import annotations

from typing import Any, Callable

import pandas as pd


def grid_search_swing(
    df: pd.DataFrame,
    param_grid: dict[str, list[Any]],
    backtest_fn: Callable[..., dict[str, Any]],
) -> pd.DataFrame:
    """Simple grid search over interpretable parameters."""
    from itertools import product

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    rows = []
    for combo in product(*values):
        params = dict(zip(keys, combo, strict=False))
        result = backtest_fn(**params)
        rows.append({**params, **result.get("metrics", {})})
    return pd.DataFrame(rows)
