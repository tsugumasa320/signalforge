"""Strategy execution order for long experiment campaigns."""

from __future__ import annotations

ML_HEAVY_STYLES = frozenset({"swing_champion", "swing_high_winrate"})


def sort_strategies_for_campaign(
    strategy_ids: list[str],
    catalog_by_id: dict[str, dict],
) -> list[str]:
    """Non-ML styles first, then ML-heavy; stable within each bucket."""

    def sort_key(sid: str) -> tuple[int, str, str]:
        style = str((catalog_by_id.get(sid) or {}).get("style") or "swing")
        ml_bucket = 1 if style in ML_HEAVY_STYLES else 0
        return (ml_bucket, style, sid)

    return sorted(strategy_ids, key=sort_key)
