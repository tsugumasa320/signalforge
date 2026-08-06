from __future__ import annotations

import numpy as np
import pandas as pd


def triple_barrier_labels(
    df: pd.DataFrame,
    events: pd.DatetimeIndex,
    side: pd.Series,
    tp_mult: float = 2.0,
    sl_mult: float = 1.0,
    max_hold: int = 10,
) -> pd.DataFrame:
    """
    Triple barrier labeling: +1 TP hit, -1 SL hit, 0 timeout.
    """
    labels = []
    for ts in events:
        if ts not in df.index:
            continue
        idx = df.index.get_loc(ts)
        if idx + 1 >= len(df):
            continue
        s = side.loc[ts] if ts in side.index else 1
        entry = df.iloc[idx]["close"]
        atr = df.iloc[idx]["atr_14"]
        if pd.isna(atr) or atr <= 0:
            continue
        if s > 0:
            tp = entry + atr * tp_mult
            sl = entry - atr * sl_mult
        else:
            tp = entry - atr * tp_mult
            sl = entry + atr * sl_mult

        label = 0
        for j in range(idx + 1, min(idx + 1 + max_hold, len(df))):
            row = df.iloc[j]
            if s > 0:
                if row["high"] >= tp:
                    label = 1
                    break
                if row["low"] <= sl:
                    label = -1
                    break
            else:
                if row["low"] <= tp:
                    label = 1
                    break
                if row["high"] >= sl:
                    label = -1
                    break

        meta = 1 if label == 1 else 0
        labels.append({"timestamp": ts, "label": label, "meta_label": meta, "side": s})

    return pd.DataFrame(labels).set_index("timestamp") if labels else pd.DataFrame()
