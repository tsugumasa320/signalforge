"""Execution window, budgets, and throttling for experiment campaigns."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

from signalforge.config import CONFIG_DIR, load_yaml


def load_schedule() -> dict[str, Any]:
    path = CONFIG_DIR / "experiments" / "schedule.yaml"
    if not path.exists():
        return {}
    return load_yaml(path)


def _parse_hhmm(s: str | None) -> dt_time | None:
    if not s or str(s).lower() in ("null", "none", ""):
        return None
    parts = str(s).strip().split(":")
    h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    return dt_time(h, m)


def within_active_hours(now: datetime, start: dt_time | None, end: dt_time | None) -> bool:
    if start is None and end is None:
        return True
    t = now.timetz().replace(tzinfo=None) if hasattr(now, "timetz") else now.time()
    if start is not None and end is not None:
        if start <= end:
            return start <= t <= end
        return t >= start or t <= end
    if start is not None:
        return t >= start
    if end is not None:
        return t <= end
    return True


@dataclass
class ExecutionBudget:
    timezone: str = "Asia/Tokyo"
    max_strategies_per_run: int = 0
    max_tickers_per_strategy: int = 0
    max_minutes_per_run: float = 0
    sleep_seconds_per_ticker: float = 0
    sleep_seconds_per_strategy: float = 0
    ticker_progress_every: int = 100
    checkpoint_every: int = 50
    parallel_workers: int = 0
    active_start: dt_time | None = None
    active_end: dt_time | None = None
    started_monotonic: float = field(default_factory=time.monotonic)

    @classmethod
    def from_config(
        cls,
        schedule_doc: dict[str, Any] | None = None,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> ExecutionBudget:
        doc = schedule_doc if schedule_doc is not None else load_schedule()
        ex = doc.get("execution") or {}
        ah = ex.get("active_hours") or {}
        ov = overrides or {}

        def _int(key: str, default: int) -> int:
            v = ov.get(key, ex.get(key, default))
            return int(v) if v is not None else default

        def _float(key: str, default: float) -> float:
            v = ov.get(key, ex.get(key, default))
            return float(v) if v is not None else default

        return cls(
            timezone=str(ov.get("timezone", ex.get("timezone", "Asia/Tokyo"))),
            max_strategies_per_run=_int("max_strategies_per_run", 0),
            max_tickers_per_strategy=_int("max_tickers_per_strategy", 0),
            max_minutes_per_run=_float("max_minutes_per_run", 0),
            sleep_seconds_per_ticker=_float("sleep_seconds_per_ticker", 0),
            sleep_seconds_per_strategy=_float("sleep_seconds_per_strategy", 0),
            ticker_progress_every=_int("ticker_progress_every", 100),
            checkpoint_every=_int("checkpoint_every", 50),
            parallel_workers=_int("parallel_workers", 0),
            active_start=_parse_hhmm(ov.get("active_hours_start", ah.get("start"))),
            active_end=_parse_hhmm(ov.get("active_hours_end", ah.get("end"))),
        )

    def now_local(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    def check_may_run(self, *, ignore_window: bool = False) -> tuple[bool, str]:
        if ignore_window:
            return True, ""
        if not within_active_hours(self.now_local(), self.active_start, self.active_end):
            s = self.active_start.isoformat() if self.active_start else "—"
            e = self.active_end.isoformat() if self.active_end else "—"
            return (
                False,
                f"実行時間外（許可: {s}〜{e} {self.timezone}）。"
                " schedule.yaml を編集するか --ignore-schedule",
            )
        return True, ""

    def time_exhausted(self) -> bool:
        if self.max_minutes_per_run <= 0:
            return False
        elapsed = (time.monotonic() - self.started_monotonic) / 60.0
        return elapsed >= self.max_minutes_per_run

    def strategies_budget_remaining(self, processed_new: int) -> bool:
        if self.max_strategies_per_run <= 0:
            return True
        return processed_new < self.max_strategies_per_run

    def sleep_after_ticker(self) -> None:
        if self.sleep_seconds_per_ticker > 0:
            time.sleep(self.sleep_seconds_per_ticker)

    def sleep_after_strategy(self) -> None:
        if self.sleep_seconds_per_strategy > 0:
            time.sleep(self.sleep_seconds_per_strategy)

    def to_manifest_fragment(self) -> dict[str, Any]:
        return {
            "timezone": self.timezone,
            "max_strategies_per_run": self.max_strategies_per_run,
            "max_tickers_per_strategy": self.max_tickers_per_strategy,
            "max_minutes_per_run": self.max_minutes_per_run,
            "sleep_seconds_per_ticker": self.sleep_seconds_per_ticker,
            "sleep_seconds_per_strategy": self.sleep_seconds_per_strategy,
            "parallel_workers": self.parallel_workers,
            "active_hours": {
                "start": self.active_start.isoformat() if self.active_start else None,
                "end": self.active_end.isoformat() if self.active_end else None,
            },
        }
