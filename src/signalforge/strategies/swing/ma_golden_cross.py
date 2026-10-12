from __future__ import annotations

import pandas as pd

from signalforge.interpret.audit import RuleCheck
from signalforge.strategies.base import BaseStrategy


class MaGoldenCrossStrategy(BaseStrategy):
    """Short/medium EMA golden cross with EMA75 trend filter (common JP swing pattern)."""

    name = "ma_golden_cross"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        params = self.cfg.get("strategy_params", {})
        adx_min = float(params.get("adx_min", 0))
        long_only = bool(params.get("long_only", True))
        require_close_above_75 = bool(params.get("require_close_above_ema75", True))

        signals = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            ts = df.index[i]

            gc = prev["ema5"] <= prev["ema25"] and row["ema5"] > row["ema25"]
            dc = prev["ema5"] >= prev["ema25"] and row["ema5"] < row["ema25"]
            trend_up = row["close"] > row["ema75"] if require_close_above_75 else True
            trend_down = row["close"] < row["ema75"] if require_close_above_75 else True
            adx_val = float(row.get("adx_14", 0))
            adx_ok = adx_val > adx_min if adx_min > 0 else True

            checks = [
                RuleCheck("ema5 golden cross ema25", gc),
                RuleCheck("close > ema75", trend_up),
                RuleCheck(
                    f"adx > {adx_min:.0f}" if adx_min > 0 else "adx filter off",
                    adx_ok,
                    detail=f"adx={adx_val:.1f}" if not adx_ok else "",
                ),
            ]

            if gc and trend_up and adx_ok:
                signals.iloc[i] = 1
                self._record_audit(ts, "long", checks)
            elif any(c.passed for c in checks):
                self._record_audit(ts, "long", checks)
            elif dc and trend_down and adx_ok and not long_only:
                signals.iloc[i] = -1
                self._record_audit(
                    ts,
                    "short",
                    [RuleCheck("ema5 dead cross ema25", True), RuleCheck("close < ema75", True)],
                )

        return signals
