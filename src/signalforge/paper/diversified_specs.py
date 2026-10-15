"""Diversified forward paper matrix (style, strategy, cohort)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiversifiedPaperSpec:
    style: str
    strategy: str
    cohort: str = "prime"


# プライム主力（テンプレ被りを抑えた7本 + ベンチ1）
DIVERSIFIED_PAPER_SIMULATIONS: list[DiversifiedPaperSpec] = [
    DiversifiedPaperSpec("swing", "bb_lower_rsi_oversold", "prime"),
    DiversifiedPaperSpec("swing", "bnf_ma25_kairi_reversion", "prime"),
    DiversifiedPaperSpec("swing", "low_pbr_value_reversal", "prime"),
    DiversifiedPaperSpec("swing", "bnf_multi_indicator_bounce", "prime"),
    DiversifiedPaperSpec("swing", "macd_cross", "prime"),
    DiversifiedPaperSpec("swing", "kabutan_preset_rsi_oversold", "growth"),
    DiversifiedPaperSpec("swing", "ichimoku_tk_cross", "growth"),
]


def as_tuples() -> list[tuple[str, str]]:
    return [(s.style, s.strategy) for s in DIVERSIFIED_PAPER_SIMULATIONS]
