from __future__ import annotations

import pandas as pd

from signalforge.interpret.audit import RuleCheck
from signalforge.strategies.base import BaseStrategy


class EmaPullbackStrategy(BaseStrategy):
    name = "ema_pullback"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        adx_threshold = float(self.rules.get("long", [{}])[-1].split(">")[-1].strip() if isinstance(self.rules.get("long"), list) else 25)
        for key in self.rules.get("long", []):
            if "adx" in key and ">" in key:
                adx_threshold = float(key.split(">")[-1].strip())
                break

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            ts = df.index[i]

            c1 = RuleCheck("close > ema200", bool(row["close"] > row["ema200"]))
            c2 = RuleCheck(
                "low touches ema20",
                bool(row["low"] <= row["ema20"] * 1.002 and row["close"] > row["ema20"]),
            )
            c3 = RuleCheck("close > ema20", bool(row["close"] > row["ema20"]))
            adx_val = row.get("adx_14", 0)
            c4 = RuleCheck(
                "adx > 25",
                bool(adx_val > adx_threshold),
                detail=f"adx > {adx_threshold} (actual: {adx_val:.1f})" if adx_val <= adx_threshold else "",
            )
            checks = [c1, c2, c3, c4]

            if all(c.passed for c in checks):
                signals.iloc[i] = 1
                self._record_audit(ts, "long", checks)
            elif any(c.passed for c in checks):
                self._record_audit(ts, "long", checks)

        return signals
