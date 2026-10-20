from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from signalforge.interpret.audit import RuleCheck
from signalforge.strategies.base import BaseStrategy
from signalforge.strategies.intraday_signals import (
    opening_gap_session,
    pivot_bounce,
    prior_day_level_break,
    psar_flip,
    session_high_break,
    session_momentum,
    session_vwap_fade,
)


def _cross_up(prev_a: float, prev_b: float, a: float, b: float) -> bool:
    return prev_a <= prev_b and a > b


def _cross_down(prev_a: float, prev_b: float, a: float, b: float) -> bool:
    return prev_a >= prev_b and a < b


class CatalogTemplateStrategy(BaseStrategy):
    """Parameterized templates for web_catalog strategy IDs."""

    name = "catalog_template"

    def __init__(self, cfg: dict[str, Any]) -> None:
        super().__init__(cfg)
        self.template = cfg.get("_catalog_template", "momentum_ema")
        cid = cfg.get("_catalog_id")
        if cid:
            self.name = str(cid)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        params = self.cfg.get("strategy_params", {})
        fn = _TEMPLATE_REGISTRY.get(self.template)
        if fn is None:
            raise ValueError(f"Unknown catalog template: {self.template}")
        return fn(df, params, self)


def _ma_cross(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    fast = params.get("fast", "ema20")
    slow = params.get("slow", "ema50")
    direction = params.get("direction", "golden")
    long_only = bool(params.get("long_only", True))
    trend_col = params.get("trend_col")
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        fa, fb = float(prev[fast]), float(prev[slow])
        ca, cb = float(row[fast]), float(row[slow])
        gc = _cross_up(fa, fb, ca, cb)
        dc = _cross_down(fa, fb, ca, cb)
        trend_ok = True
        if trend_col:
            trend_ok = float(row["close"]) > float(row[trend_col])
        if direction == "golden" and gc and trend_ok:
            signals.iloc[i] = 1
            strat._record_audit(df.index[i], "long", [RuleCheck("ma golden cross", True)])
        elif direction == "dead" and dc and not long_only:
            signals.iloc[i] = -1
    return signals


def _perfect_order_pullback(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row = df.iloc[i]
        order = row["ema5"] > row["ema25"] > row["ema75"]
        pullback = row["low"] <= row["ema25"] and row["close"] > row["ema25"]
        if order and pullback:
            signals.iloc[i] = 1
    return signals


def _rsi_oversold(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    rsi_max = float(params.get("rsi_max", 30))
    rsi_reclaim = float(params.get("rsi_reclaim", rsi_max))
    require_ema200 = bool(params.get("require_ema200", False))
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        reclaim = float(prev["rsi_14"]) < rsi_max and float(row["rsi_14"]) >= rsi_reclaim
        ema_ok = row["close"] > row.get("ema200", row["close"]) if require_ema200 else True
        if reclaim and ema_ok:
            signals.iloc[i] = 1
    return signals


def _rsi_momentum(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    rsi_min = float(params.get("rsi_min", 60))
    ema_col = params.get("ema_col", "ema25")
    signal = params.get("signal", "long")
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row = df.iloc[i]
        strong = float(row["rsi_14"]) >= rsi_min and float(row["close"]) > float(row.get(ema_col, row["close"]))
        if signal == "long" and strong:
            signals.iloc[i] = 1
        elif signal == "exit_short" and float(row["rsi_14"]) >= rsi_min:
            signals.iloc[i] = -1
    return signals


def _mean_reversion_rsi(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    return _rsi_oversold(df, {"rsi_max": 35, "rsi_reclaim": 35, **params}, strat)


def _bb_rsi(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    side = params.get("side", "lower")
    signals = pd.Series(0, index=df.index)
    rsi_max = float(params.get("rsi_max", 30))
    rsi_min = float(params.get("rsi_min", 70))
    for i in range(1, len(df)):
        row = df.iloc[i]
        if side == "lower" and row["close"] <= row["bb_lower"] and float(row["rsi_14"]) <= rsi_max:
            signals.iloc[i] = 1
        if side == "upper" and row["close"] >= row["bb_upper"] and float(row["rsi_14"]) >= rsi_min:
            signals.iloc[i] = -1 if params.get("signal") == "short" else 0
    return signals


def _volume_breakout(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    vr_min = float(params.get("volume_ratio_min", 1.5))
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        vol_ok = float(row.get("volume_ratio_20", 0)) >= vr_min
        break_up = row["close"] > prev["high"]
        if vol_ok and break_up:
            signals.iloc[i] = 1
    return signals


def _donchian_breakout(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    period = int(params.get("period", 20))
    col = f"donchian_high_{period}"
    if col not in df.columns:
        col = "donchian_high_20"
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        if row["close"] > prev.get(col, prev["high"]):
            signals.iloc[i] = 1
    return signals


def _adx_trend(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    adx_min = float(params.get("adx_min", 25))
    ema_col = params.get("ema_col", "ema50")
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row = df.iloc[i]
        if float(row["adx_14"]) >= adx_min and float(row["close"]) > float(row.get(ema_col, row["close"])):
            signals.iloc[i] = 1
    return signals


def _momentum_ema(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    ema_col = params.get("ema_col", "ema20")
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        if row["close"] > row.get(ema_col, row["close"]) and row["close"] > prev["close"]:
            signals.iloc[i] = 1
    return signals


def _high_breakout_rsi(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    lookback = int(params.get("lookback", 126))
    rsi_min = float(params.get("rsi_min", 60))
    roll_high = df["high"].rolling(lookback).max()
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row = df.iloc[i]
        near_high = row["close"] >= float(roll_high.iloc[i - 1]) * 0.98
        if near_high and float(row["rsi_14"]) >= rsi_min:
            signals.iloc[i] = 1
    return signals


def _gap_up(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    min_gap = float(params.get("min_gap_pct", 0.01))
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        gap = (row["open"] - prev["close"]) / prev["close"]
        if gap >= min_gap and row["close"] > row["open"]:
            signals.iloc[i] = 1
    return signals


def _gap_fill_reversal(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        gap_down = row["open"] < prev["close"]
        fill = row["high"] >= prev["close"]
        if gap_down and fill and row["close"] > row["open"]:
            signals.iloc[i] = 1
    return signals


def _macd_histogram_reversal(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        turn = float(prev["macd_histogram"]) < 0 and float(row["macd_histogram"]) > 0
        if turn and float(row["macd"]) > float(row["macd_signal"]):
            signals.iloc[i] = 1
    return signals


def _combo_macd_rsi(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        gc = _cross_up(float(prev["macd"]), float(prev["macd_signal"]), float(row["macd"]), float(row["macd_signal"]))
        rsi_ok = 45 <= float(row["rsi_14"]) <= 70
        if gc and rsi_ok and row["close"] > row["ema50"]:
            signals.iloc[i] = 1
    return signals


def _combo_macd_rsi_ichimoku(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    base = _combo_macd_rsi(df, params, strat)
    if "ichimoku_span_a" not in df.columns:
        return base
    filtered = base.copy()
    for i in range(len(df)):
        if filtered.iloc[i] == 1:
            row = df.iloc[i]
            cloud_top = max(float(row["ichimoku_span_a"]), float(row["ichimoku_span_b"]))
            if float(row["close"]) <= cloud_top:
                filtered.iloc[i] = 0
    return filtered


def _ema200_filter_macd(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        gc = _cross_up(float(prev["macd"]), float(prev["macd_signal"]), float(row["macd"]), float(row["macd_signal"]))
        if gc and row["close"] > row["ema200"]:
            signals.iloc[i] = 1
    return signals


def _kairi_mean_reversion(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    ema_col = params.get("ema_col", "ema25")
    kairi_max = float(params.get("kairi_max_pct", -2.0))
    trend_ema = params.get("trend_ema")
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row = df.iloc[i]
        ema_v = float(row.get(ema_col, row["close"]))
        kairi = (float(row["close"]) - ema_v) / ema_v * 100
        trend_ok = float(row["close"]) > float(row[trend_ema]) if trend_ema else True
        if kairi <= kairi_max and trend_ok:
            signals.iloc[i] = 1
    return signals


def _three_bar_reversal(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    direction = params.get("direction", "bearish")
    signals = pd.Series(0, index=df.index)
    for i in range(3, len(df)):
        w = df.iloc[i - 3 : i]
        if direction == "bearish":
            highs_rising = w["high"].iloc[0] < w["high"].iloc[1] < w["high"].iloc[2]
            bear = df.iloc[i]["close"] < df.iloc[i]["open"]
            if highs_rising and bear:
                signals.iloc[i] = -1
    return signals


def _heikin_ashi_trend(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    if "ha_close" not in df.columns:
        return _momentum_ema(df, {"ema_col": "ema20"}, strat)
    signals = pd.Series(0, index=df.index)
    for i in range(2, len(df)):
        row = df.iloc[i]
        if row["ha_close"] > row["ha_open"] and df.iloc[i - 1]["ha_close"] > df.iloc[i - 1]["ha_open"]:
            signals.iloc[i] = 1
    return signals


def _ichimoku_kumo_break(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    if "ichimoku_span_a" not in df.columns:
        return _momentum_ema(df, {"ema_col": "ema50"}, strat)
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        cloud_top = max(float(row["ichimoku_span_a"]), float(row["ichimoku_span_b"]))
        prev_top = max(float(prev["ichimoku_span_a"]), float(prev["ichimoku_span_b"]))
        cross = float(prev["close"]) <= prev_top and float(row["close"]) > cloud_top
        if cross:
            signals.iloc[i] = 1
    return signals


def _ichimoku_sanyaku(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    if "ichimoku_tenkan" not in df.columns:
        return _ichimoku_kumo_break(df, params, strat)
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row = df.iloc[i]
        cloud_top = max(float(row["ichimoku_span_a"]), float(row["ichimoku_span_b"]))
        sanyaku = (
            row["ichimoku_tenkan"] > row["ichimoku_kijun"]
            and row["close"] > cloud_top
            and row["close"] > row["ichimoku_tenkan"]
        )
        if sanyaku:
            signals.iloc[i] = 1
    return signals


def _ichimoku_tk_cross(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        if _cross_up(
            float(prev["ichimoku_tenkan"]),
            float(prev["ichimoku_kijun"]),
            float(row["ichimoku_tenkan"]),
            float(row["ichimoku_kijun"]),
        ):
            signals.iloc[i] = 1
    return signals


def _ichimoku_kijun_pullback(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row = df.iloc[i]
        cloud_top = max(float(row["ichimoku_span_a"]), float(row["ichimoku_span_b"]))
        touch = row["low"] <= row["ichimoku_kijun"] and row["close"] > row["ichimoku_kijun"]
        if touch and row["close"] > cloud_top:
            signals.iloc[i] = 1
    return signals


def _cci_cross(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    if "cci_20" not in df.columns:
        return _rsi_oversold(df, {}, strat)
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        if float(prev["cci_20"]) < 0 and float(row["cci_20"]) >= 0:
            signals.iloc[i] = 1
    return signals


def _swing_pullback_ema(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    ema_col = params.get("ema_col", "ema20")
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row = df.iloc[i]
        if row["low"] <= row.get(ema_col, row["close"]) and row["close"] > row.get(ema_col, row["close"]):
            signals.iloc[i] = 1
    return signals


def _bb_squeeze_proxy(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    signals = pd.Series(0, index=df.index)
    width = df["bb_width"].rolling(20).mean()
    for i in range(21, len(df)):
        row = df.iloc[i]
        squeeze = row["bb_width"] < width.iloc[i - 1]
        expand = row["close"] > row["bb_mid"]
        if squeeze and expand:
            signals.iloc[i] = 1
    return signals


def _vwap_proxy_daily(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    mode = params.get("mode", "pullback")
    col = "vwap" if "vwap" in df.columns else "ema20"
    signals = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        row = df.iloc[i]
        if mode == "pullback" and row["low"] <= row[col] and row["close"] > row[col]:
            signals.iloc[i] = 1
        elif mode == "breakout" and row["close"] > row[col] and row["close"] > df.iloc[i - 1]["close"]:
            signals.iloc[i] = 1
        elif mode == "mean_rev_short" and row["close"] < row[col]:
            signals.iloc[i] = -1
    return signals


def _ema_pullback_proxy(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    return _swing_pullback_ema(df, {"ema_col": "ema20"}, strat)


def _sector_relative_momentum(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    lookback = int(params.get("lookback", 20))
    col = f"sector_rs_{lookback}d"
    min_rs = float(params.get("min_rs_pct", 1.0))
    ema_col = params.get("ema_col", "ema20")
    signals = pd.Series(0, index=df.index)
    if col not in df.columns:
        return signals
    for i in range(1, len(df)):
        row = df.iloc[i]
        rs = row.get(col)
        if rs is None or rs != rs or float(rs) < min_rs:
            continue
        if float(row["close"]) > float(row.get(ema_col, row["close"])):
            signals.iloc[i] = 1
    return signals


def _sector_spread_zscore(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    z_col = params.get("z_col", "sector_spread_z20")
    entry_z = float(params.get("entry_z", -2.0))
    exit_z = float(params.get("exit_z", 0.0))
    signals = pd.Series(0, index=df.index)
    if z_col not in df.columns:
        return signals
    for i in range(1, len(df)):
        z = df.iloc[i][z_col]
        if z is None or z != z:
            continue
        zf = float(z)
        if zf <= entry_z:
            signals.iloc[i] = 1
        elif zf >= exit_z:
            signals.iloc[i] = -1
    return signals


def _credit_margin_contrarian(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    """High short margin ratio that starts falling → contrarian long (需給改善期待)."""
    min_ratio = float(params.get("min_shrt_ratio", 0.45))
    min_drop = float(params.get("ratio_drop", 0.03))
    rsi_max = float(params.get("rsi_max", 45))
    chg_col = params.get("chg_col", "margin_shrt_ratio_chg_4w")
    signals = pd.Series(0, index=df.index)
    if "margin_shrt_ratio" not in df.columns:
        return signals
    for i in range(1, len(df)):
        row = df.iloc[i]
        ratio = row.get("margin_shrt_ratio")
        chg = row.get(chg_col) if chg_col in df.columns else None
        if ratio is None or ratio != ratio or float(ratio) < min_ratio:
            continue
        if chg is None or chg != chg or float(chg) > -min_drop:
            continue
        rsi = row.get("rsi_14")
        rsi_ok = rsi is None or rsi != rsi or float(rsi) <= rsi_max
        if rsi_ok and float(row["close"]) >= float(row.get("ema20", row["close"])):
            signals.iloc[i] = 1
    return signals


def _post_earnings_drift(df: pd.DataFrame, params: dict, strat: BaseStrategy) -> pd.Series:
    min_day = int(params.get("min_days_after", 1))
    max_day = int(params.get("max_days_after", 5))
    min_gap = float(params.get("min_gap_pct", 0.005))
    vol_ratio = float(params.get("volume_ratio_min", 1.2))
    signals = pd.Series(0, index=df.index)
    if "days_since_earnings" not in df.columns:
        return signals
    vol_ma = df["volume"].rolling(20).mean()
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        dse = row.get("days_since_earnings")
        if dse is None or dse != dse:
            continue
        days = int(float(dse))
        if days < min_day or days > max_day:
            continue
        gap = (row["open"] - prev["close"]) / prev["close"]
        vma = vol_ma.iloc[i]
        vol_ok = vma == vma and float(row["volume"]) >= float(vma) * vol_ratio
        if gap >= min_gap and row["close"] > row["open"] and vol_ok:
            signals.iloc[i] = 1
    return signals


_TEMPLATE_REGISTRY: dict[str, Callable[..., pd.Series]] = {
    "ma_cross": _ma_cross,
    "perfect_order_pullback": _perfect_order_pullback,
    "rsi_oversold": _rsi_oversold,
    "rsi_momentum": _rsi_momentum,
    "mean_reversion_rsi": _mean_reversion_rsi,
    "bb_rsi": _bb_rsi,
    "volume_breakout": _volume_breakout,
    "donchian_breakout": _donchian_breakout,
    "adx_trend": _adx_trend,
    "momentum_ema": _momentum_ema,
    "high_breakout_rsi": _high_breakout_rsi,
    "gap_up": _gap_up,
    "gap_fill_reversal": _gap_fill_reversal,
    "macd_histogram_reversal": _macd_histogram_reversal,
    "combo_macd_rsi": _combo_macd_rsi,
    "combo_macd_rsi_ichimoku": _combo_macd_rsi_ichimoku,
    "ema200_filter_macd": _ema200_filter_macd,
    "kairi_mean_reversion": _kairi_mean_reversion,
    "three_bar_reversal": _three_bar_reversal,
    "heikin_ashi_trend": _heikin_ashi_trend,
    "ichimoku_kumo_break": _ichimoku_kumo_break,
    "ichimoku_sanyaku": _ichimoku_sanyaku,
    "ichimoku_tk_cross": _ichimoku_tk_cross,
    "ichimoku_kijun_pullback": _ichimoku_kijun_pullback,
    "cci_cross": _cci_cross,
    "swing_pullback_ema": _swing_pullback_ema,
    "bb_squeeze_proxy": _bb_squeeze_proxy,
    "vwap_proxy_daily": _vwap_proxy_daily,
    "session_vwap": _vwap_proxy_daily,
    "opening_gap_session": opening_gap_session,
    "prior_day_level_break": prior_day_level_break,
    "session_high_break": session_high_break,
    "session_momentum": session_momentum,
    "session_vwap_fade": session_vwap_fade,
    "pivot_bounce": pivot_bounce,
    "psar_flip": psar_flip,
    "ema_pullback_proxy": _ema_pullback_proxy,
    "sector_relative_momentum": _sector_relative_momentum,
    "sector_spread_zscore": _sector_spread_zscore,
    "post_earnings_drift": _post_earnings_drift,
    "credit_margin_contrarian": _credit_margin_contrarian,
}


def resolve_catalog_strategy(catalog_id: str, cfg: dict[str, Any]) -> BaseStrategy:
    from signalforge.config import load_implementation_map

    impl = load_implementation_map()
    entry = impl.get("strategies", {}).get(catalog_id)
    if not entry:
        raise ValueError(f"No implementation map for catalog id: {catalog_id}")

    if entry.get("builtin"):
        from signalforge.strategies.registry import STRATEGY_REGISTRY

        cls = STRATEGY_REGISTRY[entry["builtin"]]
        merged = {**cfg, "strategy_params": {**cfg.get("strategy_params", {}), **entry.get("params", {})}}
        return cls(merged)

    if entry.get("template") == "builtin_macd":
        from signalforge.strategies.registry import STRATEGY_REGISTRY

        merged = {**cfg, "strategy_params": {**cfg.get("strategy_params", {}), **entry.get("params", {})}}
        return STRATEGY_REGISTRY["macd_cross"](merged)

    merged = {
        **cfg,
        "strategy_params": {**cfg.get("strategy_params", {}), **entry.get("params", {})},
        "_catalog_template": entry["template"],
        "_catalog_id": catalog_id,
        "_approximation": entry.get("approximation"),
    }
    return CatalogTemplateStrategy(merged)
