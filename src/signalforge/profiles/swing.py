from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from signalforge.profiles.base import StyleProfile


@dataclass
class SwingProfile(StyleProfile):
    max_open_positions: int = 1

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> SwingProfile:
        bt = cfg.get("backtest", {})
        return cls(
            name="swing",
            timeframe=cfg.get("timeframe", "1d"),
            max_hold_bars=bt.get("max_hold_bars", cfg.get("rules", {}).get("exit", {}).get("max_hold_bars", 15)),
            slippage_pct=bt.get("slippage_pct", 0.0005),
            fill_mode=bt.get("fill", "next_day_open"),
            max_open_positions=bt.get("max_open_positions", 1),
        )

    def apply_session_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def entry_fill_price(self, df: pd.DataFrame, bar_idx: int, side: str) -> float:
        if bar_idx + 1 >= len(df):
            return float(df.iloc[bar_idx]["close"])
        slip = self.slippage_pct
        price = float(df.iloc[bar_idx + 1]["open"])
        if side == "long":
            return price * (1 + slip)
        return price * (1 - slip)

    def exit_fill_price(self, df: pd.DataFrame, bar_idx: int, side: str) -> float:
        if bar_idx + 1 >= len(df):
            return float(df.iloc[bar_idx]["close"])
        slip = self.slippage_pct
        price = float(df.iloc[bar_idx + 1]["open"])
        if side == "long":
            return price * (1 - slip)
        return price * (1 + slip)

    def should_force_exit(self, df: pd.DataFrame, bar_idx: int, bars_held: int) -> bool:
        return bars_held >= self.max_hold_bars
