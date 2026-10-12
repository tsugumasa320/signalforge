from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def load_yaml(path: Path | str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_cost_config(broker: str = "alpaca") -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "costs" / f"{broker}.yaml")


def load_market_config(market: str = "japan") -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "market" / f"{market}.yaml")


def load_nvda_config() -> dict[str, Any]:
    """Legacy US/NVDA preset (deprecated — use load_market_config)."""
    path = CONFIG_DIR / "nvda.yaml"
    if path.exists():
        return load_yaml(path)
    return load_market_config("japan")


def load_universe(name: str | None = None) -> dict[str, Any]:
    if name is None:
        name = load_market_config("japan").get("universe_default", "japan_liquid")
    path = CONFIG_DIR / "universe" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Universe config not found: {path}")
    return load_yaml(path)


def load_web_catalog() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "strategies" / "web_catalog.yaml")


def load_media_sources() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "strategies" / "media_sources.yaml")


def load_implementation_map() -> dict[str, Any]:
    path = CONFIG_DIR / "strategies" / "implementation_map.yaml"
    if not path.exists():
        return {"strategies": {}}
    return load_yaml(path)


def load_backtest_defaults() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "backtest.yaml")


def market_context(cfg: dict[str, Any]) -> dict[str, Any]:
    """Ticker, timezone, correlations — from style market config."""
    return cfg.get("_market") or cfg.get("_nvda") or {}


def resolve_ticker(cfg: dict[str, Any], cfg_override: dict[str, Any] | None = None) -> str:
    if cfg_override and cfg_override.get("ticker"):
        return str(cfg_override["ticker"])
    if cfg.get("ticker"):
        return str(cfg["ticker"])
    mc = market_context(cfg)
    return str(mc.get("default_ticker") or mc.get("ticker", "7203.T"))


def load_style_config(style: str) -> dict[str, Any]:
    path = CONFIG_DIR / "styles" / f"{style}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Style config not found: {path}")
    cfg = load_yaml(path)
    market_key = cfg.get("market", "japan")
    market = load_market_config(market_key)
    cfg["_market"] = market
    cfg["_nvda"] = market  # backward compatibility
    cfg["_defaults"] = load_backtest_defaults()
    return cfg


def load_features_registry() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "features.yaml")


def project_root() -> Path:
    return ROOT


def data_dir() -> Path:
    import os

    d = os.getenv("SIGNALFORGE_DATA_DIR", str(ROOT / "data"))
    path = Path(d)
    path.mkdir(parents=True, exist_ok=True)
    return path
