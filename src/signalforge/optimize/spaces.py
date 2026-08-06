from __future__ import annotations

from typing import Any

import optuna


SWING_STRATEGIES = ("ema_pullback", "macd_cross", "bb_squeeze")
DAYTRADE_STRATEGIES = ("vwap_ema", "vwap_reclaim", "orb")


def strategies_for_style(style: str) -> tuple[str, ...]:
    if style.startswith("swing"):
        return SWING_STRATEGIES
    return DAYTRADE_STRATEGIES


def suggest_params(trial: optuna.Trial, strategy: str) -> dict[str, Any]:
    if strategy == "ema_pullback":
        return {
            "adx_threshold": trial.suggest_int("adx_threshold", 15, 35),
            "atr_tp_multiple": trial.suggest_float("atr_tp_multiple", 2.0, 5.0, step=0.5),
            "atr_sl_multiple": trial.suggest_float("atr_sl_multiple", 1.0, 2.5, step=0.25),
            "max_hold_bars": trial.suggest_int("max_hold_bars", 8, 25),
        }
    if strategy == "macd_cross":
        return {
            "adx_threshold": trial.suggest_int("adx_threshold", 18, 35),
            "ema_trend": trial.suggest_categorical("ema_trend", [50, 200]),
            "long_only": True,
            "rsi_min": trial.suggest_int("rsi_min", 35, 50),
            "rsi_max": trial.suggest_int("rsi_max", 60, 75),
            "volume_ratio_min": trial.suggest_float("volume_ratio_min", 0.0, 1.5, step=0.1),
            "require_ema200": trial.suggest_categorical("require_ema200", [True, False]),
            "require_macd_hist_positive": trial.suggest_categorical("require_macd_hist_positive", [True, False]),
            "atr_tp_multiple": trial.suggest_float("atr_tp_multiple", 1.5, 2.5, step=0.25),
            "atr_sl_multiple": trial.suggest_float("atr_sl_multiple", 1.0, 1.5, step=0.25),
            "min_probability": trial.suggest_float("min_probability", 0.52, 0.65, step=0.01),
        }
    if strategy == "bb_squeeze":
        return {
            "adx_threshold": trial.suggest_int("adx_threshold", 15, 35),
            "squeeze_lookback": trial.suggest_int("squeeze_lookback", 10, 30),
        }
    return {"adx_threshold": trial.suggest_int("adx_threshold", 15, 35)}


def build_cfg_override(strategy: str, params: dict[str, Any], base_cfg: dict[str, Any]) -> dict[str, Any]:
    rules = dict(base_cfg.get("rules", {}))
    exit_rules = dict(rules.get("exit", {}))
    strategy_params = dict(base_cfg.get("strategy_params", {}))

    if strategy == "ema_pullback":
        adx = int(params["adx_threshold"])
        rules["long"] = [
            "close > ema200",
            "low touches ema20",
            "close > ema20",
            f"adx > {adx}",
        ]
        exit_rules["atr_tp_multiple"] = float(params["atr_tp_multiple"])
        exit_rules["atr_sl_multiple"] = float(params["atr_sl_multiple"])
        exit_rules["max_hold_bars"] = int(params["max_hold_bars"])
        rules["exit"] = exit_rules
        return {"rules": rules, "backtest": {**base_cfg.get("backtest", {}), "max_hold_bars": int(params["max_hold_bars"])}}

    if strategy == "macd_cross":
        adx = int(params["adx_threshold"])
        strategy_params.update(
            {
                "ema_trend": int(params["ema_trend"]),
                "adx_min": adx,
                "long_only": bool(params.get("long_only", True)),
                "rsi_min": float(params.get("rsi_min", 0)),
                "rsi_max": float(params.get("rsi_max", 100)),
                "volume_ratio_min": float(params.get("volume_ratio_min", 0)),
                "require_ema200": bool(params.get("require_ema200", False)),
                "require_macd_hist_positive": bool(params.get("require_macd_hist_positive", False)),
            }
        )
        exit_rules["atr_tp_multiple"] = float(params.get("atr_tp_multiple", exit_rules.get("atr_tp_multiple", 3.0)))
        exit_rules["atr_sl_multiple"] = float(params.get("atr_sl_multiple", exit_rules.get("atr_sl_multiple", 1.5)))
        rules["exit"] = exit_rules
        if adx > 0:
            rules["long"] = [f"adx > {adx}"]
        out: dict[str, Any] = {"rules": rules, "strategy_params": strategy_params}
        if "min_probability" in params:
            out["ml_filter"] = {
                **base_cfg.get("ml_filter", {}),
                "min_probability": float(params["min_probability"]),
            }
        return out

    if strategy == "bb_squeeze":
        adx = int(params["adx_threshold"])
        strategy_params["squeeze_lookback"] = int(params["squeeze_lookback"])
        rules["long"] = [
            "bb squeeze release",
            f"adx > {adx}",
        ]
        return {"rules": rules, "strategy_params": strategy_params}

    return {}
