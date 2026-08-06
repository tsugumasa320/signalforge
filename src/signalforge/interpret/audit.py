from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleCheck:
    rule: str
    passed: bool
    detail: str = ""


@dataclass
class SignalAuditResult:
    timestamp: str
    side: str
    all_passed: bool
    checks: list[RuleCheck] = field(default_factory=list)

    @property
    def passed_rules(self) -> list[str]:
        return [c.rule for c in self.checks if c.passed]

    @property
    def failed_rules(self) -> list[str]:
        out = []
        for c in self.checks:
            if not c.passed:
                out.append(c.detail or c.rule)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "side": self.side,
            "all_passed": self.all_passed,
            "rules_audit": {
                "passed": self.passed_rules,
                "failed": self.failed_rules,
            },
        }


class SignalAudit:
    """Record which rules passed/failed for each signal candidate."""

    def __init__(self) -> None:
        self.records: list[SignalAuditResult] = []

    def record(self, result: SignalAuditResult) -> None:
        self.records.append(result)

    def for_timestamp(self, ts: str) -> list[SignalAuditResult]:
        return [r for r in self.records if r.timestamp == ts]

    def clear(self) -> None:
        self.records.clear()
