"""Helpers for the AI trial dashboard panel."""

from __future__ import annotations

from signalforge.report.dashboard_ai import _stance_emoji


def test_stance_emoji() -> None:
    assert _stance_emoji("ADOPT").startswith("🟢")
    assert _stance_emoji("HOLD").startswith("🟡")
    assert _stance_emoji("AVOID").startswith("🔴")
