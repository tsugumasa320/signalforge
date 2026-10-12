from __future__ import annotations

from typing import Any

from signalforge.config import CONFIG_DIR, load_universe, load_yaml


def load_equity_meta() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "universe" / "japan_equity_meta.yaml")


def load_compare_presets() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "universe" / "compare_presets.yaml")


def _tag_set(meta: dict[str, Any]) -> set[str]:
    return set(meta.get("tags") or [])


def resolve_cohort_tickers(filter_spec: dict[str, Any] | None) -> list[str]:
    """Return tickers matching filter keys: segment, sector_tse, tags, universe."""
    spec = filter_spec or {}
    equity = load_equity_meta()
    all_meta: dict[str, dict] = equity.get("tickers", {})

    universe_name = spec.get("universe")
    universe_set: set[str] | None = None
    if universe_name:
        universe_set = set(load_universe(universe_name).get("tickers", []))

    out: list[str] = []
    for sym, meta in all_meta.items():
        if universe_set is not None and sym not in universe_set:
            continue
        segments = spec.get("segment")
        if segments and meta.get("segment") not in segments:
            continue
        sectors = spec.get("sector_tse")
        if sectors and meta.get("sector_tse") not in sectors:
            continue
        req_tags = spec.get("tags")
        if req_tags and not _tag_set(meta).intersection(req_tags):
            continue
        exclude_tags = spec.get("exclude_tags")
        if exclude_tags and _tag_set(meta).intersection(exclude_tags):
            continue
        if spec.get("exclude_etf") and meta.get("sector_tse") == "ETF":
            continue
        out.append(sym)
    return sorted(out)


def get_preset(preset_id: str) -> dict[str, Any]:
    doc = load_compare_presets()
    for p in doc.get("presets", []):
        if p.get("id") == preset_id:
            return p
    raise KeyError(f"Unknown compare preset: {preset_id}")


def list_preset_ids() -> list[tuple[str, str]]:
    doc = load_compare_presets()
    return [(p["id"], p.get("label", p["id"])) for p in doc.get("presets", [])]


def cohorts_by_dimension(dimension: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Auto cohorts: segment | sector_tse."""
    equity = load_equity_meta()
    meta = equity.get("tickers", {})
    if dimension == "segment":
        values = sorted({m.get("segment") for m in meta.values() if m.get("segment")})
        return [
            (f"segment_{v}", f"市場区分 — {v}", {"segment": [v], "exclude_etf": True})
            for v in values
        ]
    if dimension == "sector_tse":
        values = sorted({m.get("sector_tse") for m in meta.values() if m.get("sector_tse")})
        return [
            (f"sector_{v}", f"業種 — {v}", {"sector_tse": [v], "exclude_etf": True})
            for v in values
        ]
    raise ValueError(f"Unknown dimension: {dimension}")
