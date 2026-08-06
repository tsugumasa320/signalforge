from __future__ import annotations

import pandas as pd

from signalforge.data.calendar import days_to_next_earnings
from signalforge.interpret.features_registry import allowed_feature_names, validate_features


def build_features(
    df: pd.DataFrame,
    qqq_df: pd.DataFrame | None = None,
    soxx_df: pd.DataFrame | None = None,
    intraday: bool = False,
) -> pd.DataFrame:
    names = allowed_feature_names()
    feat = pd.DataFrame(index=df.index)

    mapping = {
        "adx_14": "adx_14",
        "rsi_14": "rsi_14",
        "ema20_distance_pct": "ema20_distance_pct",
        "macd_histogram": "macd_histogram",
        "atr_pct": "atr_pct",
        "volume_ratio_20": "volume_ratio_20",
    }
    for out_col, src_col in mapping.items():
        if src_col in df.columns and out_col in names:
            feat[out_col] = df[src_col]

    if "qqq_relative_strength" in names and qqq_df is not None:
        aligned = qqq_df["close"].reindex(df.index, method="ffill")
        feat["qqq_relative_strength"] = df["close"] / aligned

    if "soxx_relative_strength" in names and soxx_df is not None:
        aligned = soxx_df["close"].reindex(df.index, method="ffill")
        feat["soxx_relative_strength"] = df["close"] / aligned

    if "days_to_earnings" in names:
        feat["days_to_earnings"] = df.index.map(days_to_next_earnings)

    if intraday and "hour_of_day" in names:
        idx = df.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        feat["hour_of_day"] = idx.tz_convert("America/New_York").hour

    validate_features(list(feat.columns))
    return feat.dropna(how="all")
