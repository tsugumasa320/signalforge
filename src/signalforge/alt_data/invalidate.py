"""Drop saved experiment JSON so strategies re-backtest after alt-data / logic changes."""

from __future__ import annotations

from pathlib import Path

from signalforge.alt_data.deps import data_deps_for_strategy
from signalforge.config import load_implementation_map
from signalforge.experiments.runner import clear_strategy_checkpoints, experiments_dir


def invalidate_strategy_results(strategy_id: str) -> None:
    clear_strategy_checkpoints(strategy_id)
    d = experiments_dir() / "strategies"
    for name in (
        f"{strategy_id}.json",
        f"{strategy_id}.tickers.json",
    ):
        Path(d / name).unlink(missing_ok=True)


def invalidate_trusted_alt_strategies() -> list[str]:
    from signalforge.alt_data.trust import strategies_ready_for_rerun

    touched: list[str] = []
    for sid in strategies_ready_for_rerun():
        invalidate_strategy_results(sid)
        touched.append(sid)
    return touched


def invalidate_alt_data_strategies() -> list[str]:
    impl = load_implementation_map().get("strategies") or {}
    touched: list[str] = []
    for sid in sorted(impl.keys()):
        if not data_deps_for_strategy(sid):
            continue
        invalidate_strategy_results(sid)
        touched.append(sid)
    return touched
