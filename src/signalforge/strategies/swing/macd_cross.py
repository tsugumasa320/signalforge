from __future__ import annotations

import pandas as pd

from signalforge.interpret.audit import RuleCheck
from signalforge.strategies.base import BaseStrategy

_EMA_COLUMNS = {20: "ema20", 50: "ema50", 200: "ema200"}


class MacdCrossStrategy(BaseStrategy):
    name = "macd_cross"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        params = self.cfg.get("strategy_params", {})
        ema_period = int(params.get("ema_trend", 50))
        ema_col = _EMA_COLUMNS.get(ema_period, "ema50")
        adx_min = float(params.get("adx_min", 0))
        long_only = bool(params.get("long_only", False))
        rsi_min = float(params.get("rsi_min", 0))
        rsi_max = float(params.get("rsi_max", 100))
        volume_ratio_min = float(params.get("volume_ratio_min", 0))
        require_ema200 = bool(params.get("require_ema200", False))
        require_macd_hist = bool(params.get("require_macd_hist_positive", False))

        signals = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            ts = df.index[i]

            gc = prev["macd"] <= prev["macd_signal"] and row["macd"] > row["macd_signal"]
            dc = prev["macd"] >= prev["macd_signal"] and row["macd"] < row["macd_signal"]
            ema_val = row.get(ema_col, row.get("ema50", row["close"]))
            trend_up = row["close"] > ema_val
            trend_down = row["close"] < ema_val

            adx_val = float(row.get("adx_14", 0))
            adx_ok = adx_val > adx_min if adx_min > 0 else True
            rsi_val = float(row.get("rsi_14", 50))
            rsi_ok = rsi_min <= rsi_val <= rsi_max
            vol_ratio = float(row.get("volume_ratio_20", 1))
            vol_ok = vol_ratio >= volume_ratio_min if volume_ratio_min > 0 else True
            ema200_ok = row["close"] > row.get("ema200", row["close"]) if require_ema200 else True
            hist_ok = float(row.get("macd_histogram", 0)) > 0 if require_macd_hist else True

            checks = [
                RuleCheck("macd golden cross", gc),
                RuleCheck(f"close > {ema_col}", trend_up),
                RuleCheck(
                    f"adx > {adx_min:.0f}" if adx_min > 0 else "adx filter off",
                    adx_ok,
                    detail=f"adx={adx_val:.1f}" if not adx_ok else "",
                ),
                RuleCheck(f"rsi {rsi_min:.0f}-{rsi_max:.0f}", rsi_ok, detail=f"rsi={rsi_val:.1f}" if not rsi_ok else ""),
                RuleCheck(f"volume ratio >= {volume_ratio_min:.1f}", vol_ok, detail=f"vol={vol_ratio:.2f}" if not vol_ok else ""),
                RuleCheck("close > ema200", ema200_ok),
                RuleCheck("macd histogram > 0", hist_ok),
            ]

            if gc and trend_up and adx_ok and rsi_ok and vol_ok and ema200_ok and hist_ok:
                signals.iloc[i] = 1
                self._record_audit(ts, "long", checks)
            elif gc and trend_up and any(c.passed for c in checks):
                self._record_audit(ts, "long", checks)
            elif dc and trend_down and adx_ok and not long_only:
                short_checks = [
                    RuleCheck("macd dead cross", True),
                    RuleCheck(f"close < {ema_col}", True),
                    checks[2],
                ]
                signals.iloc[i] = -1
                self._record_audit(ts, "short", short_checks)

        return signals
