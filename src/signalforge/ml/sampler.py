from __future__ import annotations

import numpy as np
import pandas as pd


def cusum_filter(
    returns: pd.Series,
    threshold: float = 0.02,
) -> pd.DatetimeIndex:
    """Event-based sampling using CUSUM filter (Lopez de Prado)."""
    t_events = []
    s_pos = 0.0
    s_neg = 0.0
    diff = returns.diff().dropna()
    for ts, ret in diff.items():
        s_pos = max(0, s_pos + ret)
        s_neg = min(0, s_neg + ret)
        if s_pos > threshold:
            t_events.append(ts)
            s_pos = 0.0
        elif s_neg < -threshold:
            t_events.append(ts)
            s_neg = 0.0
    return pd.DatetimeIndex(t_events)
