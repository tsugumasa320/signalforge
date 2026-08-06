from __future__ import annotations

from typing import Any, Callable

import optuna


def bayesian_optimize(
    objective_fn: Callable[[optuna.Trial], float],
    n_trials: int = 50,
    direction: str = "maximize",
    seed: int = 42,
) -> dict[str, Any]:
    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction=direction, sampler=sampler)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study.optimize(objective_fn, n_trials=n_trials, show_progress_bar=False)
    return {
        "best_params": study.best_params,
        "best_value": study.best_value,
        "n_trials": len(study.trials),
    }
