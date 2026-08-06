from __future__ import annotations

import pandas as pd

from signalforge.indicators.engine import IndicatorEngine
from signalforge.interpret.audit import RuleCheck
from signalforge.strategies.base import BaseStrategy


class BbSqueezeStrategy(BaseStrategy):
    name = "bb_squeeze"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        engine = IndicatorEngine(shift=0)
        pct = engine.bb_width_percentile(df)
        df = df.copy()
        df["bb_width_pct"] = pct.shift(1)

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            ts = df.index[i]
            if pd.isna(row.get("bb_width_pct")):
                continue

            squeeze = row["bb_width_pct"] < 20
            break_up = row["close"] > row["bb_upper"] and prev["close"] <= prev["bb_upper"]
            break_down = row["close"] < row["bb_lower"] and prev["close"] >= prev["bb_lower"]

            if squeeze and break_up:
                checks = [
                    RuleCheck("bb width percentile < 20", True),
                    RuleCheck("breakout above upper band", True),
                ]
                signals.iloc[i] = 1
                self._record_audit(ts, "long", checks)
            elif squeeze and break_down:
                checks = [
                    RuleCheck("bb width percentile < 20", True),
                    RuleCheck("breakout below lower band", True),
                ]
                signals.iloc[i] = -1
                self._record_audit(ts, "short", checks)

        return signals
