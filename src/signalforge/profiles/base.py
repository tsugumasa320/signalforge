from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class StyleProfile(ABC):
    name: str
    timeframe: str
    max_hold_bars: int
    slippage_pct: float
    fill_mode: str

    @abstractmethod
    def apply_session_filter(self, df):  # noqa: ANN001
        ...

    @abstractmethod
    def entry_fill_price(self, df, bar_idx: int, side: str):  # noqa: ANN001
        ...

    @abstractmethod
    def should_force_exit(self, df, bar_idx: int, bars_held: int) -> bool:  # noqa: ANN001
        ...

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> StyleProfile:
        style = cfg.get("style", "swing")
        if style == "daytrade":
            from signalforge.profiles.daytrade import DaytradeProfile

            return DaytradeProfile.from_config(cfg)
        from signalforge.profiles.swing import SwingProfile

        return SwingProfile.from_config(cfg)
