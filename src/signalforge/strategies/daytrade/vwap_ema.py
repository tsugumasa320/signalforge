from __future__ import annotations

import pandas as pd

from signalforge.interpret.audit import RuleCheck
from signalforge.strategies.base import BaseStrategy


class VwapEmaStrategy(BaseStrategy):
    name = "vwap_ema"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        vol_mult = 1.5

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            ts = df.index[i]

            if "vwap" not in row or pd.isna(row["vwap"]):
                continue

            ema_cross_up = prev["ema9"] <= prev["ema21"] and row["ema9"] > row["ema21"]
            ema_cross_down = prev["ema9"] >= prev["ema21"] and row["ema9"] < row["ema21"]
            vol_ok = row["volume"] > row["volume_ma20"] * vol_mult

            long_checks = [
                RuleCheck("close > vwap", bool(row["close"] > row["vwap"])),
                RuleCheck("ema9 crosses_above ema21", bool(ema_cross_up)),
                RuleCheck(
                    "volume > volume_ma20 * 1.5",
                    bool(vol_ok),
                    detail=f"volume surge (ratio={row['volume']/row['volume_ma20']:.2f})" if not vol_ok else "",
                ),
            ]

            if all(c.passed for c in long_checks):
                signals.iloc[i] = 1
                self._record_audit(ts, "long", long_checks)
            elif ema_cross_up or row["close"] > row["vwap"]:
                self._record_audit(ts, "long", long_checks)

            short_checks = [
                RuleCheck("close < vwap", bool(row["close"] < row["vwap"])),
                RuleCheck("ema9 crosses_below ema21", bool(ema_cross_down)),
                RuleCheck("volume > volume_ma20 * 1.5", bool(vol_ok)),
            ]
            if all(c.passed for c in short_checks):
                signals.iloc[i] = -1
                self._record_audit(ts, "short", short_checks)

        return signals
