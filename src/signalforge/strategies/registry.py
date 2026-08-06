from __future__ import annotations

from typing import Any

from signalforge.strategies.base import BaseStrategy
from signalforge.strategies.daytrade.orb import OrbStrategy
from signalforge.strategies.daytrade.vwap_ema import VwapEmaStrategy
from signalforge.strategies.daytrade.vwap_reclaim import VwapReclaimStrategy
from signalforge.strategies.swing.bb_squeeze import BbSqueezeStrategy
from signalforge.strategies.swing.ema_pullback import EmaPullbackStrategy
from signalforge.strategies.swing.macd_cross import MacdCrossStrategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "ema_pullback": EmaPullbackStrategy,
    "macd_cross": MacdCrossStrategy,
    "bb_squeeze": BbSqueezeStrategy,
    "vwap_ema": VwapEmaStrategy,
    "vwap_reclaim": VwapReclaimStrategy,
    "orb": OrbStrategy,
}


def get_strategy(name: str, cfg: dict[str, Any]) -> BaseStrategy:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY)}")
    return STRATEGY_REGISTRY[name](cfg)
