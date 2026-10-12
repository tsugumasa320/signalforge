from __future__ import annotations

import pandas as pd

from signalforge.interpret.audit import RuleCheck
from signalforge.strategies.base import BaseStrategy


class RsiReversalStrategy(BaseStrategy):
    """RSI oversold bounce — cross back above threshold in an uptrend."""

    name = "rsi_reversal"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        params = self.cfg.get("strategy_params", {})
        rsi_oversold = float(params.get("rsi_oversold", 30))
        rsi_reclaim = float(params.get("rsi_reclaim", 30))
        require_ema200 = bool(params.get("require_ema200", True))
        adx_min = float(params.get("adx_min", 0))
        long_only = bool(params.get("long_only", True))

        signals = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            ts = df.index[i]

            prev_rsi = float(prev.get("rsi_14", 50))
            rsi_val = float(row.get("rsi_14", 50))
            reclaim = prev_rsi < rsi_oversold and rsi_val >= rsi_reclaim
            ema200_ok = row["close"] > row.get("ema200", row["close"]) if require_ema200 else True
            adx_val = float(row.get("adx_14", 0))
            adx_ok = adx_val > adx_min if adx_min > 0 else True

            checks = [
                RuleCheck(f"rsi reclaim {rsi_reclaim:.0f}", reclaim, detail=f"rsi={rsi_val:.1f}"),
                RuleCheck("close > ema200", ema200_ok),
                RuleCheck(
                    f"adx > {adx_min:.0f}" if adx_min > 0 else "adx filter off",
                    adx_ok,
                    detail=f"adx={adx_val:.1f}" if not adx_ok else "",
                ),
            ]

            if reclaim and ema200_ok and adx_ok:
                signals.iloc[i] = 1
                self._record_audit(ts, "long", checks)
            elif any(c.passed for c in checks):
                self._record_audit(ts, "long", checks)

            if not long_only and prev_rsi > (100 - rsi_oversold) and rsi_val <= (100 - rsi_reclaim):
                if row["close"] < row.get("ema200", row["close"]):
                    signals.iloc[i] = -1

        return signals
