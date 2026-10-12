from __future__ import annotations

from typing import Any

from signalforge.config import CONFIG_DIR, load_yaml


def load_palette() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "lab" / "izanami_palette.yaml")


def list_palette_rules() -> list[dict[str, Any]]:
    return list(load_palette().get("rules", []))


def resolve_palette_rule(rule_id: str) -> dict[str, Any]:
    for r in list_palette_rules():
        if r.get("id") == rule_id:
            base = load_palette()
            return {
                **r,
                "id": rule_id,
                "defaults": base.get("defaults", {}),
            }
    raise KeyError(f"Unknown lab rule: {rule_id}")


def resolve_rule_ids(spec: str) -> list[str]:
    if spec.strip().lower() in ("all", "*"):
        return [r["id"] for r in list_palette_rules()]
    return [x.strip() for x in spec.split(",") if x.strip()]
