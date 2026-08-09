"""Champion preset — best validated NVDA swing configuration in this repo."""

from __future__ import annotations

from typing import Any

from signalforge.config import load_style_config
from signalforge.optimize.spaces import build_cfg_override

# Bayesian + manual tuning on NVDA 2023+ (Alpaca costs): PF ~4.1, win ~72%
CHAMPION_MACD_PARAMS: dict[str, Any] = {
    "adx_threshold": 23,
    "ema_trend": 200,
    "long_only": True,
    "atr_tp_multiple": 2.0,
    "atr_sl_multiple": 1.5,
    "max_hold_bars": 12,
}

CHAMPION_STYLE = "swing_champion"
CHAMPION_STRATEGY = "macd_cross"


def champion_cfg_override(style: str, strategy: str, base_cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return cfg override for macd_cross when champion preset applies."""
    if strategy != "macd_cross":
        return None
    if style in (CHAMPION_STYLE, "swing_high_winrate"):
        return None  # YAML already encodes champion rules
    if style.startswith("swing"):
        cfg = base_cfg or load_style_config(style)
        return build_cfg_override("macd_cross", CHAMPION_MACD_PARAMS, cfg)
    return None


def pipeline_kwargs(style: str, strategy: str | None, cfg_override: dict[str, Any] | None) -> dict[str, Any]:
    """Merge champion override unless caller already supplied one."""
    if cfg_override is not None:
        return {"cfg_override": cfg_override}
    strat = strategy or "ema_pullback"
    override = champion_cfg_override(style, strat)
    return {"cfg_override": override} if override else {}
