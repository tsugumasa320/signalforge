from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from signalforge.interpret.audit import RuleCheck, SignalAudit, SignalAuditResult


@dataclass
class SignalResult:
    side: str  # long, short, flat
    bar_idx: int
    timestamp: pd.Timestamp
    audit: SignalAuditResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    name: str = "base"

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.rules = cfg.get("rules", {})
        self.audit = SignalAudit()

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return 1 long, -1 short, 0 flat."""
        ...

    def _record_audit(
        self,
        ts: pd.Timestamp,
        side: str,
        checks: list[RuleCheck],
    ) -> None:
        result = SignalAuditResult(
            timestamp=str(ts),
            side=side,
            all_passed=all(c.passed for c in checks),
            checks=checks,
        )
        self.audit.record(result)

    def summary_ja(self, audit: SignalAuditResult, extra: str = "") -> str:
        if audit.all_passed:
            base = f"{self.name} 成立（{', '.join(audit.passed_rules[:3])}）"
        else:
            base = f"{self.name} 不成立（{', '.join(audit.failed_rules[:2])}）"
        return f"{base}{extra}"
