"""Trend-screen DUKE Stage2 gates for lab preset switching."""

from __future__ import annotations

import numpy as np
import pandas as pd

from signalforge.research.trend_screen.ranking import (
    DUKE_LAB_GATE_KEYS,
    TREND_LAB_GATE_KEYS,
    _duke_gate_snapshot,
)


def test_duke_gate_keys_disjoint_from_trend():
    assert not (set(DUKE_LAB_GATE_KEYS) & set(TREND_LAB_GATE_KEYS))


def test_duke_gate_snapshot_uptrend():
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    px = pd.Series(np.linspace(80, 150, 300), index=idx)
    vol = pd.Series(1e6, index=idx)
    vol.iloc[-1] = 2.5e6
    bench = pd.Series(np.linspace(100, 120, 300), index=idx)
    out = _duke_gate_snapshot(px, vol, bench, 299, float(px.iloc[299]))
    assert out["gates"]["duke_above_sma150_200"]
    assert out["gates"]["duke_volume_surge"]
    assert out["duke_score"] is not None and out["duke_score"] > 0
