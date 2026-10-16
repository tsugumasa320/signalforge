"""Diversified forward paper matrix (style, strategy, cohort)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiversifiedPaperSpec:
    style: str
    strategy: str
    cohort: str = "prime"


# プライム5 + growth2（1口座・中央値のバランス、BB/MACD ベンチは外す）
DIVERSIFIED_PAPER_SIMULATIONS: list[DiversifiedPaperSpec] = [
    DiversifiedPaperSpec("swing", "bnf_ma25_kairi_reversion", "prime"),
    DiversifiedPaperSpec("swing", "bnf_multi_indicator_bounce", "prime"),
    DiversifiedPaperSpec("swing", "low_pbr_value_reversal", "prime"),
    DiversifiedPaperSpec("swing", "gap_fill_reversal", "prime"),
    DiversifiedPaperSpec("swing", "mean_reversion_short_term", "prime"),
    DiversifiedPaperSpec("swing", "kabutan_preset_rsi_oversold", "growth"),
    DiversifiedPaperSpec("swing", "ichimoku_tk_cross", "growth"),
]


def as_tuples() -> list[tuple[str, str]]:
    return [(s.style, s.strategy) for s in DIVERSIFIED_PAPER_SIMULATIONS]
