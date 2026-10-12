from __future__ import annotations

from typing import Any

from signalforge.strategies.base import BaseStrategy
from signalforge.strategies.daytrade.orb import OrbStrategy
from signalforge.strategies.daytrade.vwap_ema import VwapEmaStrategy
from signalforge.strategies.daytrade.vwap_reclaim import VwapReclaimStrategy
from signalforge.strategies.swing.bb_squeeze import BbSqueezeStrategy
from signalforge.strategies.swing.ema_pullback import EmaPullbackStrategy
from signalforge.strategies.swing.ma_golden_cross import MaGoldenCrossStrategy
from signalforge.strategies.swing.macd_cross import MacdCrossStrategy
from signalforge.strategies.swing.rsi_reversal import RsiReversalStrategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "ema_pullback": EmaPullbackStrategy,
    "macd_cross": MacdCrossStrategy,
    "ma_golden_cross": MaGoldenCrossStrategy,
    "rsi_reversal": RsiReversalStrategy,
    "bb_squeeze": BbSqueezeStrategy,
    "vwap_ema": VwapEmaStrategy,
    "vwap_reclaim": VwapReclaimStrategy,
    "orb": OrbStrategy,
}


def get_strategy(name: str, cfg: dict[str, Any]) -> BaseStrategy:
    if name in STRATEGY_REGISTRY:
        return STRATEGY_REGISTRY[name](cfg)
    from signalforge.config import load_implementation_map

    if name in load_implementation_map().get("strategies", {}):
        from signalforge.strategies.catalog_template import resolve_catalog_strategy

        return resolve_catalog_strategy(name, cfg)
    raise ValueError(
        f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY)} + catalog IDs in implementation_map.yaml"
    )
