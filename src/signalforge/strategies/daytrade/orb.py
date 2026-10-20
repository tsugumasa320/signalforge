from __future__ import annotations

import pandas as pd

from signalforge.interpret.audit import RuleCheck
from signalforge.strategies.base import BaseStrategy


def opening_range_bars(index: pd.Index, or_minutes: int) -> int:
    """How many bars cover the opening range. 5-minute data is 4 bars for 20 minutes; 1-minute data is 20."""
    if or_minutes <= 0:
        return 4
    if len(index) < 2:
        return max(1, or_minutes // 5)
    diffs = pd.Series(index).diff().dt.total_seconds().div(60.0)
    usable = diffs[(diffs > 0) & (diffs <= 30)]
    minutes = float(usable.median()) if len(usable) else 5.0
    if minutes != minutes or minutes <= 0:
        minutes = 5.0
    return max(1, int(round(or_minutes / minutes)))


class OrbStrategy(BaseStrategy):
    name = "orb"

    def __init__(self, cfg, or_minutes: int = 20) -> None:
        super().__init__(cfg)
        self.or_minutes = or_minutes
        from signalforge.config import market_context

        self.timezone = market_context(cfg).get("timezone", "Asia/Tokyo")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        idx = df.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        local = idx.tz_convert(self.timezone)
        dates = local.date

        for d in pd.unique(dates):
            day_mask = dates == d
            day_df = df.loc[day_mask]
            if len(day_df) < 5:
                continue

            or_bars = min(opening_range_bars(day_df.index, self.or_minutes), len(day_df) // 2)
            or_slice = day_df.iloc[:or_bars]
            or_high = or_slice["high"].max()
            or_low = or_slice["low"].min()

            for i in range(or_bars, len(day_df)):
                global_idx = df.index.get_loc(day_df.index[i])
                row = df.iloc[global_idx]
                ts = df.index[global_idx]
                vol_ok = row["volume"] > row["volume_ma20"] * 1.2

                if row["close"] > or_high and vol_ok:
                    checks = [
                        RuleCheck("break above opening range high", True),
                        RuleCheck("volume confirmation", True),
                    ]
                    signals.iloc[global_idx] = 1
                    self._record_audit(ts, "long", checks)
                elif row["close"] < or_low and vol_ok:
                    checks = [
                        RuleCheck("break below opening range low", True),
                        RuleCheck("volume confirmation", True),
                    ]
                    signals.iloc[global_idx] = -1
                    self._record_audit(ts, "short", checks)

        return signals
