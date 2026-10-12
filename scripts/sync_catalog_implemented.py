#!/usr/bin/env python3
"""Mark catalog entries as implemented when listed in implementation_map.yaml."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "strategies" / "web_catalog.yaml"
MAP = ROOT / "config" / "strategies" / "implementation_map.yaml"


def main() -> int:
    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}
    impl = yaml.safe_load(MAP.read_text(encoding="utf-8")) or {}
    mapped = set(impl.get("strategies", {}).keys())
    n = 0
    for s in cat.get("strategies", []):
        if s["id"] in mapped:
            s["implemented"] = True
            entry = impl["strategies"][s["id"]]
            if entry.get("approximation"):
                s["implementation_note"] = str(entry["approximation"])
            n += 1
    CATALOG.write_text(yaml.safe_dump(cat, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Marked {n} strategies implemented in catalog")
    return 0


if __name__ == "__main__":
    sys.exit(main())
