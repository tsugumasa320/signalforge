"""Composable entry conditions (Izanami palette-style DSL)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _col(df: pd.DataFrame, i: int, name: str) -> float:
    return float(df.iloc[i].get(name, float("nan")))


def _eval_one(df: pd.DataFrame, i: int, cond: dict[str, Any]) -> bool:
    lag = int(cond.get("bars_ago", cond.get("shift", 0)))
    idx = i - lag
    if idx < 1 or idx >= len(df):
        return False

    op = cond["op"]
    row = df.iloc[idx]
    prev = df.iloc[idx - 1]

    if op == "cross_up":
        a, b = cond["left"], cond["right"]
        return _col(df, idx - 1, a) <= _col(df, idx - 1, b) and _col(df, idx, a) > _col(df, idx, b)
    if op == "cross_down":
        a, b = cond["left"], cond["right"]
        return _col(df, idx - 1, a) >= _col(df, idx - 1, b) and _col(df, idx, a) < _col(df, idx, b)
    if op == "gt_col":
        return _col(df, idx, cond["col"]) > _col(df, idx, cond["ref"])
    if op == "lt_col":
        return _col(df, idx, cond["col"]) < _col(df, idx, cond["ref"])
    if op == "gt":
        return _col(df, idx, cond["col"]) > float(cond["value"])
    if op == "lt":
        return _col(df, idx, cond["col"]) < float(cond["value"])
    if op == "between":
        v = _col(df, idx, cond["col"])
        return float(cond["min"]) <= v <= float(cond["max"])
    if op == "volume_ratio_gte":
        return _col(df, idx, "volume_ratio_20") >= float(cond.get("value", 1.5))
    if op == "pct_change_gte":
        pct = (row["close"] - prev["close"]) / prev["close"] * 100
        return pct >= float(cond["value"])
    if op == "high_breakout":
        n = int(cond.get("lookback", 20))
        if idx < n:
            return False
        prev_high = float(df["high"].iloc[idx - n : idx].max())
        return float(row["close"]) > prev_high
    if op == "bb_touch_lower":
        return float(row["close"]) <= float(row["bb_lower"])
    if op == "bb_touch_upper":
        return float(row["close"]) >= float(row["bb_upper"])
    if op == "ichimoku_above_cloud":
        top = max(float(row["ichimoku_span_a"]), float(row["ichimoku_span_b"]))
        return float(row["close"]) > top
    if op == "harami_bullish":
        # 前日長い陰線・当日小さい実体が前日レンジ内（簡易はらみ）
        if idx < 1:
            return False
        p, c = prev, row
        prev_bear = p["close"] < p["open"]
        inside = c["high"] <= p["open"] and c["low"] >= p["close"]
        return prev_bear and inside
    if op == "kairi_lte":
        ema_col = cond.get("ema", "ema25")
        ema_v = _col(df, idx, ema_col)
        if ema_v == 0:
            return False
        kairi = (float(row["close"]) - ema_v) / ema_v * 100
        return kairi <= float(cond["value"])
    raise ValueError(f"Unknown condition op: {op}")


def eval_group(df: pd.DataFrame, i: int, group: dict[str, Any]) -> bool:
    if "all" in group:
        return all(_eval_one(df, i, c) for c in group["all"])
    if "any" in group:
        return any(_eval_one(df, i, c) for c in group["any"])
    if "op" in group:
        return _eval_one(df, i, group)
    return False


def signals_from_entry_spec(df: pd.DataFrame, entry: dict[str, Any]) -> pd.Series:
    signals = pd.Series(0, index=df.index)
    for i in range(len(df)):
        if eval_group(df, i, entry):
            signals.iloc[i] = 1
    return signals
