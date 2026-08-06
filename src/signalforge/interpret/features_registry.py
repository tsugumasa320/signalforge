from __future__ import annotations

from signalforge.config import load_features_registry


def get_feature_descriptions() -> dict[str, str]:
    reg = load_features_registry()
    allowed = reg.get("allowed_features", {})
    return {k: v.get("desc", k) if isinstance(v, dict) else str(v) for k, v in allowed.items()}


def allowed_feature_names() -> list[str]:
    reg = load_features_registry()
    return list(reg.get("allowed_features", {}).keys())


def validate_features(names: list[str]) -> list[str]:
    allowed = set(allowed_feature_names())
    invalid = [n for n in names if n not in allowed]
    if invalid:
        raise ValueError(f"Features not in registry: {invalid}")
    return names
