from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any

import pandas as pd

from signalforge.profiles.base import StyleProfile


@dataclass
class DaytradeProfile(StyleProfile):
    session_start: time = time(9, 30)
    session_end: time = time(15, 55)
    force_flat_time: time = time(15, 55)
    max_trades_per_day: int = 3
    timezone: str = "America/New_York"

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> DaytradeProfile:
        bt = cfg.get("backtest", {})
        exit_rules = cfg.get("rules", {}).get("exit", {})
        ff = exit_rules.get("force_flat_time", "15:55")
        h, m = map(int, ff.split(":"))
        ss = bt.get("session_start", "09:30")
        se = bt.get("session_end", "15:55")
        sh, sm = map(int, ss.split(":"))
        eh, em = map(int, se.split(":"))
        nvda = cfg.get("_nvda", {})
        return cls(
            name="daytrade",
            timeframe=cfg.get("timeframe", "5m"),
            max_hold_bars=bt.get("max_hold_bars", exit_rules.get("max_hold_bars", 12)),
            slippage_pct=bt.get("slippage_pct", 0.0002),
            fill_mode=bt.get("fill", "next_bar_open"),
            session_start=time(sh, sm),
            session_end=time(eh, em),
            force_flat_time=time(h, m),
            max_trades_per_day=bt.get("max_trades_per_day", 3),
            timezone=nvda.get("timezone", "America/New_York"),
        )

    def apply_session_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        idx = df.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        local = idx.tz_convert(self.timezone)
        times = local.time
        mask = (times >= self.session_start) & (times <= self.session_end)
        return df.loc[mask]

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
        if bars_held >= self.max_hold_bars:
            return True
        ts = df.index[bar_idx]
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        local = ts.tz_convert(self.timezone)
        if local.time() >= self.force_flat_time:
            return True
        return False

    def is_in_session(self, ts: pd.Timestamp) -> bool:
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        local = ts.tz_convert(self.timezone)
        t = local.time()
        return self.session_start <= t <= self.session_end
