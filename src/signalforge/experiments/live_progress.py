"""Terminal live progress (stdlib only) for long experiment campaigns."""

from __future__ import annotations

import sys
import time
from datetime import datetime
from typing import Any

from signalforge.experiments.scan import scan_campaign_progress

_FRAME_LINES = 10


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds <= 0 or seconds != seconds:
        return "?"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m:02d}:{s:02d}"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h}:{m:02d}:{s:02d}"
    d, h = divmod(h, 24)
    return f"{d}d{h}h"


def format_elapsed(seconds: float) -> str:
    s = max(0, int(seconds))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_tqdm_bar(pct: float, width: int = 28) -> str:
    """tqdm 風: `` 42%|████▌             |``"""
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100.0))
    bar = "█" * filled + "░" * (width - filled)
    return f"{pct:5.1f}%|{bar}|"


def format_tqdm_line(
    desc: str,
    n: int,
    total: int,
    *,
    pct: float | None = None,
    elapsed: float | None = None,
    eta: float | None = None,
    rate: float | None = None,
    width: int = 28,
) -> str:
    if pct is None:
        pct = 100.0 * n / total if total else 0.0
    head = f"{desc:<10} {format_tqdm_bar(pct, width=width)} {n:,}/{total:,}"
    if elapsed is not None and rate is not None and rate > 0:
        tail = f" [{format_elapsed(elapsed)}<{format_eta(eta)}, {rate:.1f}it/s]"
    elif elapsed is not None:
        tail = f" [{format_elapsed(elapsed)}]"
    else:
        tail = ""
    return head + tail


def render_live_frame(
    scan: dict[str, Any],
    *,
    eta_ticker: float | None,
    rate_per_sec: float | None,
    watch_elapsed: float,
    interval: float,
) -> list[str]:
    ov = scan.get("overall") or {}
    lines: list[str] = []
    lines.append(f"TSE experiments  ·  {datetime.now().strftime('%H:%M:%S')}  ·  Ctrl+C = stop watch only")
    lines.append("")

    total_t = int(ov.get("ticker_jobs_total") or 0)
    done_t = int(ov.get("ticker_jobs_done") or 0)
    if total_t:
        lines.append(
            format_tqdm_line(
                "銘柄BT",
                done_t,
                total_t,
                pct=float(ov.get("ticker_overall_pct") or 0),
                elapsed=watch_elapsed,
                eta=eta_ticker,
                rate=rate_per_sec,
            )
        )

    n_plan = int(ov.get("strategies_planned") or 0)
    equiv = float(ov.get("strategy_equiv") or 0)
    strat_pct = float(ov.get("strategy_overall_pct") or 0)
    strat_suffix = ""
    if rate_per_sec and rate_per_sec > 0 and n_plan and total_t:
        strat_rate = rate_per_sec * n_plan / max(1, total_t // max(n_plan, 1))
        strat_eta = (n_plan - equiv) / strat_rate if equiv < n_plan else None
        strat_suffix = f" [{format_elapsed(watch_elapsed)}<{format_eta(strat_eta)}, {strat_rate:.2f}戦略/s]"
    lines.append(
        f"{'戦略':<10} {format_tqdm_bar(strat_pct)} {equiv:.2f}/{n_plan}{strat_suffix}"
    )

    sid = ov.get("active_strategy_id")
    if sid:
        ad = int(ov.get("active_n_done") or 0)
        at = max(1, int(ov.get("active_n_target") or 1))
        sp = 100.0 * ad / at
        per_strat_rate = None
        if rate_per_sec and rate_per_sec > 0:
            per_strat_rate = rate_per_sec
        lines.append(
            format_tqdm_line(
                sid[:10],
                ad,
                at,
                pct=sp,
                elapsed=watch_elapsed,
                eta=(at - ad) / per_strat_rate if per_strat_rate and ad < at else None,
                rate=per_strat_rate,
            )
        )
    else:
        lines.append("現在       （アクティブ戦略なし — 集計中 or 停止）")

    stale = ov.get("stale_checkpoints") or []
    if stale:
        parts = [f"{r['strategy_id']} {r['n_done']}/{r['n_target']}" for r in stale[:3]]
        lines.append("")
        lines.append("checkpoint 保留: " + ", ".join(parts))

    n_complete = int(ov.get("strategies_complete") or 0)
    lines.append("")
    lines.append(
        f"完了戦略 {n_complete}/{n_plan}  ·  監視 {format_elapsed(watch_elapsed)}  ·  {interval:g}s ごとに更新"
    )
    return lines


def _enter_live_terminal() -> None:
    sys.stdout.write("\033[?1049h\033[2J\033[H\033[?25l")
    sys.stdout.flush()


def _leave_live_terminal() -> None:
    sys.stdout.write("\033[?25h\033[?1049l")
    sys.stdout.flush()


def _paint_frame(lines: list[str]) -> None:
    padded = list(lines)
    while len(padded) < _FRAME_LINES:
        padded.append("")
    if len(padded) > _FRAME_LINES:
        padded = padded[:_FRAME_LINES]
    buf = ["\033[H"]
    for line in padded:
        buf.append("\033[2K")
        buf.append(line)
        buf.append("\n")
    sys.stdout.write("".join(buf))
    sys.stdout.flush()


def _run_plain_watch(*, interval: float, stop_when_complete: bool) -> None:
    """Non-TTY: single line \\r refresh."""
    prev_line = ""
    try:
        while True:
            scan = scan_campaign_progress()
            ov = scan.get("overall") or {}
            done = int(ov.get("ticker_jobs_done") or 0)
            total = int(ov.get("ticker_jobs_total") or 0)
            pct = float(ov.get("ticker_overall_pct") or 0)
            sid = ov.get("active_strategy_id") or "—"
            line = f"銘柄BT {pct:.1f}% ({done:,}/{total:,})  現在 {sid}"
            pad = max(0, len(prev_line) - len(line))
            sys.stdout.write("\r" + line + " " * pad)
            sys.stdout.flush()
            prev_line = line
            n_complete = int(ov.get("strategies_complete") or 0)
            n_plan = int(ov.get("strategies_planned") or 0)
            if stop_when_complete and n_complete >= n_plan and not scan.get("in_progress"):
                break
            time.sleep(max(1.0, interval))
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()


def run_live_watch(
    *,
    interval: float = 5.0,
    stop_when_complete: bool = False,
    use_alt_screen: bool = True,
) -> None:
    """Refresh in-place (tqdm-style) until Ctrl+C or campaign complete."""
    if not sys.stdout.isatty():
        _run_plain_watch(interval=interval, stop_when_complete=stop_when_complete)
        return

    prev_done: int | None = None
    prev_t: float | None = None
    eta: float | None = None
    rate_per_sec: float | None = None
    t0 = time.monotonic()

    if use_alt_screen:
        _enter_live_terminal()
    try:
        while True:
            scan = scan_campaign_progress()
            ov = scan.get("overall") or {}
            done = int(ov.get("ticker_jobs_done") or 0)
            total = int(ov.get("ticker_jobs_total") or 0)
            now = time.monotonic()
            watch_elapsed = now - t0

            if prev_done is not None and prev_t is not None and done > prev_done:
                dt = now - prev_t
                if dt > 0:
                    rate_per_sec = (done - prev_done) / dt
                    if total > done and rate_per_sec > 0:
                        eta = (total - done) / rate_per_sec

            prev_done, prev_t = done, now
            lines = render_live_frame(
                scan,
                eta_ticker=eta,
                rate_per_sec=rate_per_sec,
                watch_elapsed=watch_elapsed,
                interval=interval,
            )
            if use_alt_screen:
                _paint_frame(lines)
            else:
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.write("\n".join(lines) + "\n")
                sys.stdout.flush()

            n_complete = int(ov.get("strategies_complete") or 0)
            n_plan = int(ov.get("strategies_planned") or 0)
            if stop_when_complete and n_complete >= n_plan and not scan.get("in_progress"):
                break
            time.sleep(max(0.5, interval))
    except KeyboardInterrupt:
        pass
    finally:
        if use_alt_screen:
            _leave_live_terminal()
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()
