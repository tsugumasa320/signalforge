"""AI trade trial helpers — pack SignalForge outputs for LLM brief / score / debate."""

from signalforge.ai.brief import build_brief_packet, write_brief
from signalforge.ai.debate import build_debate_packet, write_debate
from signalforge.ai.score import build_score_packet, write_score

__all__ = [
    "build_brief_packet",
    "write_brief",
    "build_score_packet",
    "write_score",
    "build_debate_packet",
    "write_debate",
]
