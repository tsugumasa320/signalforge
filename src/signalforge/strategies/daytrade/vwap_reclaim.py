from __future__ import annotations

import pandas as pd

from signalforge.interpret.audit import RuleCheck
from signalforge.strategies.base import BaseStrategy


class VwapReclaimStrategy(BaseStrategy):
    name = "vwap_reclaim"

    def __init__(self, cfg, stretch_pct: float = 0.005, reclaim_pct: float = 0.003) -> None:
        super().__init__(cfg)
        self.stretch_pct = stretch_pct
        self.reclaim_pct = reclaim_pct

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        stretched = pd.Series(False, index=df.index)
        stretch_dir = pd.Series(0, index=df.index)

        for i in range(1, len(df)):
            row = df.iloc[i]
            ts = df.index[i]
            if "vwap" not in row or pd.isna(row["vwap"]):
                continue

            vwap = row["vwap"]
            dist = (row["close"] - vwap) / vwap

            if dist <= -self.stretch_pct:
                stretched.iloc[i] = True
                stretch_dir.iloc[i] = -1
            elif dist >= self.stretch_pct:
                stretched.iloc[i] = True
                stretch_dir.iloc[i] = 1

            if stretched.iloc[i - 1] and stretch_dir.iloc[i - 1] == -1:
                reclaim = (row["close"] - vwap) / vwap > -self.reclaim_pct
                if reclaim:
                    checks = [
                        RuleCheck("vwap stretch below", True),
                        RuleCheck("partial reclaim toward vwap", True),
                    ]
                    signals.iloc[i] = 1
                    self._record_audit(ts, "long", checks)

            if stretched.iloc[i - 1] and stretch_dir.iloc[i - 1] == 1:
                reclaim = (row["close"] - vwap) / vwap < self.reclaim_pct
                if reclaim:
                    checks = [
                        RuleCheck("vwap stretch above", True),
                        RuleCheck("partial reclaim toward vwap", True),
                    ]
                    signals.iloc[i] = -1
                    self._record_audit(ts, "short", checks)

        return signals
