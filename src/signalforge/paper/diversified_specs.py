"""Diversified forward paper matrix (style, strategy, cohort)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiversifiedPaperSpec:
    style: str
    strategy: str
    cohort: str = "tse_liquid"


# 1口座シム（DEFAULT_ENTRY_RULES）で前半〜2023・後半2024- とも黒字、最大DD 約-30% 以内（2026-10 再評価）
DIVERSIFIED_PAPER_SIMULATIONS: list[DiversifiedPaperSpec] = [
    DiversifiedPaperSpec("swing", "mean_reversion_short_term"),
    DiversifiedPaperSpec("swing", "cci_zero_cross"),
    DiversifiedPaperSpec("swing", "rsi_dip_200ma"),
    DiversifiedPaperSpec("swing", "bb_lower_rsi_oversold"),
    DiversifiedPaperSpec("swing", "ichimoku_tk_cross"),
    DiversifiedPaperSpec("swing", "trailing_atr_chandelier"),
    DiversifiedPaperSpec("swing", "bnf_regime_trend_vs_fade"),
]


def as_tuples() -> list[tuple[str, str]]:
    return [(s.style, s.strategy) for s in DIVERSIFIED_PAPER_SIMULATIONS]
