"""Watch TSE experiments run and restart when the BT process exits."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from signalforge.config import data_dir, project_root
from signalforge.experiments.runner import (
    default_parallel_workers,
    list_strategies_needing_metric_refresh,
    load_plan,
)
from signalforge.experiments.scan import planned_strategy_count, scan_campaign_progress

RunMode = Literal["auto", "campaign", "metrics"]

SUPERVISOR_PID_NAME = "experiments_supervisor.pid"
RUN_PID_NAME = "experiments.pid"
SUPERVISOR_LOG_NAME = "experiments_supervisor.log"
RUN_LOG_NAME = "experiments_run.log"
DEFAULT_INTERVAL_SEC = 60.0
MIN_RESTART_INTERVAL_SEC = 45.0


def reports_dir() -> Path:
    """Campaign PID/logs (same paths as scripts/run-experiments-daemon.sh)."""
    d = data_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def supervisor_pid_path() -> Path:
    return reports_dir() / SUPERVISOR_PID_NAME


def run_pid_path() -> Path:
    return reports_dir() / RUN_PID_NAME


def supervisor_log_path() -> Path:
    return reports_dir() / SUPERVISOR_LOG_NAME


def run_log_path() -> Path:
    return reports_dir() / RUN_LOG_NAME


def _log(msg: str, *, also_stdout: bool = False) -> None:
    line = f"{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')} {msg}\n"
    path = supervisor_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    if also_stdout:
        sys.stdout.write(line)
        sys.stdout.flush()


def _parse_strategy_ids_from_plan() -> list[str]:
    from signalforge.cli import _parse_strategy_ids

    plan = load_plan()
    return _parse_strategy_ids(plan.get("strategies", "catalog:all"), None, 0)


def find_experiments_run_pids() -> list[int]:
    """PIDs of `signalforge experiments run` (not supervise / watch)."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "signalforge experiments run"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    pids: list[int] = []
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pids.append(int(line))
    return pids


def is_experiments_run_alive(*, pid_file: Path | None = None) -> bool:
    if find_experiments_run_pids():
        return True
    pid_file = pid_file or run_pid_path()
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def resolve_run_mode(mode: RunMode) -> tuple[bool, str]:
    """Return (refresh_metrics, human reason fragment)."""
    if mode == "campaign":
        return False, "campaign"
    if mode == "metrics":
        return True, "refresh-metrics"
    strategy_ids = _parse_strategy_ids_from_plan()
    pending = list_strategies_needing_metric_refresh(strategy_ids)
    if pending:
        return True, f"refresh-metrics ({len(pending)} 戦略)"
    return False, "campaign"


@dataclass
class CampaignWorkStatus:
    needs_run: bool
    reason: str
    refresh_metrics: bool
    n_complete: int
    n_planned: int
    n_in_progress: int
    n_metrics_pending: int


def assess_campaign_work(*, mode: RunMode = "auto") -> CampaignWorkStatus:
    scan = scan_campaign_progress()
    n_planned = int(scan.get("total_planned") or planned_strategy_count())
    n_complete = len(scan.get("complete") or [])
    in_progress = scan.get("in_progress") or []
    n_in_progress = len(in_progress)

    strategy_ids = _parse_strategy_ids_from_plan()
    metrics_pending = list_strategies_needing_metric_refresh(strategy_ids)
    refresh_metrics, mode_tag = resolve_run_mode(mode)

    reasons: list[str] = []
    if n_complete < n_planned:
        reasons.append(f"未完了戦略 {n_planned - n_complete}/{n_planned}")
    if n_in_progress:
        reasons.append(f"checkpoint {n_in_progress} 件")
    if metrics_pending:
        reasons.append(f"指標差し替え {len(metrics_pending)} 戦略")

    needs = bool(reasons)
    if not needs:
        return CampaignWorkStatus(
            needs_run=False,
            reason="作業なし（キャンペーン完了・指標も最新）",
            refresh_metrics=False,
            n_complete=n_complete,
            n_planned=n_planned,
            n_in_progress=n_in_progress,
            n_metrics_pending=len(metrics_pending),
        )

    return CampaignWorkStatus(
        needs_run=True,
        reason=f"{mode_tag}: " + " · ".join(reasons),
        refresh_metrics=refresh_metrics,
        n_complete=n_complete,
        n_planned=n_planned,
        n_in_progress=n_in_progress,
        n_metrics_pending=len(metrics_pending),
    )


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def spawn_experiments_run(
    *,
    refresh_metrics: bool,
    workers: int,
    log_path: Path | None = None,
) -> int:
    """Start BT detached; return wrapper or python PID."""
    root = project_root()
    log_path = log_path or run_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    w = workers if workers > 0 else default_parallel_workers()
    if refresh_metrics and w > 4 and os.environ.get("EXPERIMENTS_SUPERVISOR_ALLOW_HIGH_WORKERS") != "1":
        w = min(w, 4)

    inner = [
        "uv",
        "run",
        "signalforge",
        "experiments",
        "run",
        "--ignore-schedule",
        "--workers",
        str(w),
    ]
    if refresh_metrics:
        inner.append("--refresh-metrics")

    cmd: list[str]
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        cmd = ["caffeinate", "-dims", "-s", *inner]
    else:
        cmd = inner

    with log_path.open("a", encoding="utf-8") as log_f:
        log_f.write(
            f"\n=== supervisor spawn {datetime.now(timezone.utc).astimezone().isoformat()} "
            f"workers={w} refresh_metrics={refresh_metrics} ===\n"
        )
        log_f.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

    _write_pid(run_pid_path(), proc.pid)
    return proc.pid


def supervise_loop(
    *,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
    mode: RunMode = "auto",
    workers: int = 0,
    run_once: bool = False,
) -> None:
    _write_pid(supervisor_pid_path(), os.getpid())
    _log(f"supervisor 開始 pid={os.getpid()} interval={interval_sec}s mode={mode}", also_stdout=True)

    last_spawn_at = 0.0
    try:
        while True:
            work = assess_campaign_work(mode=mode)
            if not work.needs_run:
                _log(f"待機: {work.reason}", also_stdout=True)
                if run_once:
                    return
                time.sleep(max(5.0, interval_sec))
                continue

            if is_experiments_run_alive():
                _log(f"BT 実行中 — {work.reason}")
                if run_once:
                    return
                time.sleep(max(5.0, interval_sec))
                continue

            now = time.monotonic()
            if now - last_spawn_at < MIN_RESTART_INTERVAL_SEC:
                wait = MIN_RESTART_INTERVAL_SEC - (now - last_spawn_at)
                _log(f"再開クールダウン {wait:.0f}s")
                time.sleep(wait)

            pid = spawn_experiments_run(
                refresh_metrics=work.refresh_metrics,
                workers=workers,
            )
            last_spawn_at = time.monotonic()
            _log(
                f"BT 再開 pid={pid} · {work.reason}",
                also_stdout=True,
            )

            if run_once:
                return
            time.sleep(max(5.0, interval_sec))
    finally:
        supervisor_pid_path().unlink(missing_ok=True)


def supervisor_status() -> dict[str, Any]:
    work = assess_campaign_work(mode="auto")
    return {
        "supervisor_pid_file": str(supervisor_pid_path()),
        "run_pid_file": str(run_pid_path()),
        "supervisor_log": str(supervisor_log_path()),
        "run_log": str(run_log_path()),
        "run_alive": is_experiments_run_alive(),
        "run_pids": find_experiments_run_pids(),
        "work": work,
    }
