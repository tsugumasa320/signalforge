from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def load_cost_config(broker: str = "alpaca") -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "costs" / f"{broker}.yaml")


def load_yaml(path: Path | str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_nvda_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "nvda.yaml")


def load_backtest_defaults() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "backtest.yaml")


def load_style_config(style: str) -> dict[str, Any]:
    path = CONFIG_DIR / "styles" / f"{style}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Style config not found: {path}")
    cfg = load_yaml(path)
    cfg["_nvda"] = load_nvda_config()
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
