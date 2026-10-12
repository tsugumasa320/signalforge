"""Stage-2: simplified diversified allocation (Izanami 最適分散投資の近似)."""

from __future__ import annotations

from typing import Any


def allocate_equal_weight(
    final_signals: list[dict[str, Any]],
    *,
    capital: float = 1_000_000.0,
    max_positions: int = 5,
) -> list[dict[str, Any]]:
    if not final_signals or max_positions <= 0:
        return []
    picked = final_signals[:max_positions]
    weight = capital / len(picked)
    return [
        {
            "ticker": s["ticker"],
            "instruction": "buy",
            "notional_jpy": weight,
            "reference_close": s.get("close"),
            "signal_time": s.get("time"),
        }
        for s in picked
    ]
