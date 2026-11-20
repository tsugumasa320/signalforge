"""Run the frozen STF momentum study.

Examples
--------
uv run python -m signalforge.research.stf fetch --rpm 20
uv run python -m signalforge.research.stf run
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from dataclasses import replace

from signalforge.research.stf.engine import Panel, SimResult, simulate
from signalforge.research.stf.guidance import load_disclosures, revision_map
from signalforge.research.stf.fetch import DATA, fetch_all, fetch_summaries
from signalforge.research.stf.metrics import WindowStats, summarize
from signalforge.research.stf.prepare import load_panel
from signalforge.research.stf.report import write_outputs
from signalforge.research.stf.rules import (
    EVAL_END,
    EVAL_START,
    INITIAL_CAPITAL,
    base_specs,
    earnings_specs,
    improvement_specs,
    known_limitations,
    sensitivity_specs,
)


def _parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def _headline_bounds(result: SimResult) -> tuple[date, date]:
    live = [row.day for row in result.daily if row.n_hold > 0 or row.cum_trades > 0]
    if not live:
        raise RuntimeError("どの戦略も約定しませんでした。ウォームアップ不足か、ユニバースが空です。")
    start = min(live)
    # Include the signal close, which is the session before the first trade.
    idx = next(i for i, row in enumerate(result.daily) if row.day == start)
    if idx > 0 and result.daily[idx].cum_trades > result.daily[idx - 1].cum_trades:
        start = result.daily[idx - 1].day
    end = min(result.daily[-1].day, EVAL_END)
    if start > end:
        end = result.daily[-1].day
    return start, end


def _through(panel: Panel, end: date) -> Panel:
    sessions = [day for day in panel.sessions if day <= end]
    return replace(
        panel,
        sessions=sessions,
        month_ends={day for day in panel.month_ends if day <= end},
    )


def run(capital: float, out: Path) -> None:
    panel, audit = load_panel()
    # Headline stops at the requested end so 2026 fills do not enter the 2025 figures.
    headline_panel = _through(panel, EVAL_END) if panel.sessions[-1] > EVAL_END else panel
    specs = base_specs() + sensitivity_specs()
    results = []
    for spec in specs:
        print(f"simulate {spec.name}", flush=True)
        results.append(simulate(headline_panel, spec, capital))
    anchor = next(result for result in results if result.spec.name == "A_equal_1x")
    start, end = _headline_bounds(anchor)
    stats = {result.spec.name: summarize(result, start, end, capital) for result in results}
    post_stats: dict[str, WindowStats] = {}
    if panel.sessions[-1] > EVAL_END:
        post_start = max(day for day in panel.sessions if day <= EVAL_END)
        for spec in base_specs():
            print(f"simulate post {spec.name}", flush=True)
            full = simulate(panel, spec, capital)
            try:
                post_stats[spec.name] = summarize(full, post_start, panel.sessions[-1], capital)
            except ValueError:
                continue
    write_outputs(
        out,
        results,
        stats,
        audit,
        known_limitations(),
        headline=(start, end),
        requested=(EVAL_START, EVAL_END),
        post_stats=post_stats,
        names=panel.names,
    )
    print(f"wrote {out}", flush=True)


def improve(capital: float) -> None:
    """Run the post-2025 quality revision. A and C stay as the reference."""
    panel, _audit = load_panel()
    specs = [base_specs()[0], base_specs()[2], *improvement_specs()]
    post_start = max(day for day in panel.sessions if day <= EVAL_END)
    out = DATA / "report" / "improve_summary.csv"
    lines = [
        "strategy,y2025_return,y2025_end,y2025_mdd,y2025_sharpe,y2025_avg_hold,y2026_return,y2026_mdd,bench_2025,bench_2026"
    ]
    for spec in specs:
        print(f"simulate {spec.name}", flush=True)
        result = simulate(panel, spec, capital)
        y2025 = summarize(result, date(2024, 12, 30), EVAL_END, capital)
        y2026 = summarize(result, post_start, panel.sessions[-1], capital)
        print(
            f"  2025 {y2025.total_return:+.1%} end {y2025.end_equity:,.0f} mdd {y2025.max_drawdown:.1%} "
            f"hold {y2025.avg_holdings:.1f} | 2026 {y2026.total_return:+.1%} mdd {y2026.max_drawdown:.1%}",
            flush=True,
        )
        lines.append(
            ",".join(
                [
                    spec.name,
                    f"{y2025.total_return:.6f}",
                    f"{y2025.end_equity:.0f}",
                    f"{y2025.max_drawdown:.6f}",
                    f"{y2025.sharpe:.4f}",
                    f"{y2025.avg_holdings:.3f}",
                    f"{y2026.total_return:.6f}",
                    f"{y2026.max_drawdown:.6f}",
                    f"{y2025.bench_total_return:.6f}" if y2025.bench_total_return is not None else "",
                    f"{y2026.bench_total_return:.6f}" if y2026.bench_total_return is not None else "",
                ]
            )
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}", flush=True)


def earnings(capital: float) -> None:
    """G with point-in-time guidance revisions. G itself is unchanged."""
    panel, _audit = load_panel()
    panel.revisions = revision_map(load_disclosures(), panel.sessions, sorted(panel.month_ends))
    specs = [next(spec for spec in improvement_specs() if spec.name == "G_prime_regime"), *earnings_specs()]
    post_start = max(day for day in panel.sessions if day <= EVAL_END)
    out = DATA / "report" / "earnings_summary.csv"
    lines = [
        "strategy,y2025_return,y2025_end,y2025_mdd,y2025_sharpe,y2025_avg_hold,y2026_return,y2026_mdd,bench_2025,bench_2026"
    ]
    for spec in specs:
        print(f"simulate {spec.name}", flush=True)
        result = simulate(panel, spec, capital)
        y2025 = summarize(result, date(2024, 12, 30), EVAL_END, capital)
        y2026 = summarize(result, post_start, panel.sessions[-1], capital)
        compound = y2025.end_equity / capital * (1.0 + y2026.total_return) - 1.0
        print(
            f"  2025 {y2025.total_return:+.1%} mdd {y2025.max_drawdown:.1%} hold {y2025.avg_holdings:.1f} "
            f"| 2026 {y2026.total_return:+.1%} mdd {y2026.max_drawdown:.1%} | span {compound:+.1%}",
            flush=True,
        )
        lines.append(
            ",".join(
                [
                    spec.name,
                    f"{y2025.total_return:.6f}",
                    f"{y2025.end_equity:.0f}",
                    f"{y2025.max_drawdown:.6f}",
                    f"{y2025.sharpe:.4f}",
                    f"{y2025.avg_holdings:.3f}",
                    f"{y2026.total_return:.6f}",
                    f"{y2026.max_drawdown:.6f}",
                    f"{y2025.bench_total_return:.6f}" if y2025.bench_total_return is not None else "",
                    f"{y2026.bench_total_return:.6f}" if y2026.bench_total_return is not None else "",
                ]
            )
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="STF momentum backtest (J-Quants)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--rpm", type=float, default=20.0)
    fetch.add_argument("--end", type=_parse_date, default=date(2026, 8, 15))
    run_p = sub.add_parser("run")
    run_p.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    run_p.add_argument("--out", type=Path, default=DATA / "report")
    improve_p = sub.add_parser("improve")
    improve_p.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    fins_p = sub.add_parser("fins")
    fins_p.add_argument("--rpm", type=float, default=12.0)
    earn_p = sub.add_parser("earnings")
    earn_p.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    args = parser.parse_args()
    if args.cmd == "fetch":
        note = fetch_all(rpm=args.rpm, end=args.end)
        print(json.dumps(note, ensure_ascii=False, indent=2))
        return
    if args.cmd == "fins":
        print(json.dumps(fetch_summaries(rpm=args.rpm), ensure_ascii=False))
        return
    if args.cmd == "improve":
        improve(args.capital)
        return
    if args.cmd == "earnings":
        earnings(args.capital)
        return
    run(args.capital, args.out)


if __name__ == "__main__":
    main()
