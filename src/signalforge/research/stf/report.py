"""CSV, JSON, and SVG outputs for the STF study."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from signalforge.research.stf.engine import SimResult
from signalforge.research.stf.metrics import WindowStats

_COLORS = ("#1f4e79", "#2e7d32", "#ef6c00", "#6a1b9a", "#c62828", "#455a64", "#00838f")


def _stats_row(name: str, stats: WindowStats) -> dict[str, object]:
    return {
        "strategy": name,
        "start": stats.start.isoformat(),
        "end": stats.end.isoformat(),
        "start_equity": round(stats.start_equity, 0),
        "end_equity": round(stats.end_equity, 0),
        "total_return": stats.total_return,
        "cagr": stats.cagr,
        "volatility": stats.volatility,
        "sharpe": stats.sharpe,
        "sortino": stats.sortino,
        "max_drawdown": stats.max_drawdown,
        "mdd_peak": stats.mdd_peak.isoformat() if stats.mdd_peak else "",
        "mdd_trough": stats.mdd_trough.isoformat() if stats.mdd_trough else "",
        "mdd_recovered": stats.mdd_recovered.isoformat() if stats.mdd_recovered else "",
        "max_underwater_days": stats.max_underwater_days,
        "max_down_streak_days": stats.max_down_streak,
        "trades": stats.trades,
        "trades_per_year": stats.trades_per_year,
        "avg_holdings": stats.avg_holdings,
        "avg_holding_days": stats.avg_holding_days,
        "traded_notional": round(stats.traded_notional, 0),
        "costs": round(stats.costs, 0),
        "interest": round(stats.interest, 0),
        "avg_leverage": stats.avg_leverage,
        "max_leverage": stats.max_leverage,
        "max_gross": round(stats.max_gross, 0),
        "avg_cash_ratio": stats.avg_cash_ratio,
        "min_cash_ratio": stats.min_cash_ratio,
        "avg_semi_weight": stats.avg_semi_weight,
        "avg_elec_weight": stats.avg_elec_weight,
        "avg_top_weight": stats.avg_top_weight,
        "ruined": stats.ruined,
        "bench_total_return": stats.bench_total_return,
        "bench_cagr": stats.bench_cagr,
        "excess_cagr": stats.excess_cagr,
        "yearly": {str(year): value for year, value in stats.yearly},
        "monthly": dict(stats.monthly),
    }


def _write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    lines = [",".join(columns)]
    for row in rows:
        cells = []
        for col in columns:
            value = row.get(col, "")
            text = "" if value is None else str(value)
            if "," in text:
                text = '"' + text.replace('"', '""') + '"'
            cells.append(text)
        lines.append(",".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _svg(path: Path, series: dict[str, list[float]], title: str) -> None:
    width, height = 960, 520
    left, right, top, bottom = 64, 16, 36, 40
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [v for seq in series.values() for v in seq]
    if not values:
        return
    lo, hi = min(values), max(values)
    if hi == lo:
        hi = lo + 1.0
    def xy(i: int, n: int, value: float) -> tuple[float, float]:
        x = left + (0 if n == 1 else plot_w * i / (n - 1))
        y = top + (hi - value) / (hi - lo) * plot_h
        return x, y

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{left}" y="24" font-family="sans-serif" font-size="16">{title}</text>',
    ]
    for idx, (name, seq) in enumerate(series.items()):
        color = _COLORS[idx % len(_COLORS)]
        points = " ".join(f"{xy(i, len(seq), v)[0]:.1f},{xy(i, len(seq), v)[1]:.1f}" for i, v in enumerate(seq))
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{points}"/>')
        parts.append(
            f'<text x="{left + 140 * (idx % 6)}" y="{height - 16}" font-family="sans-serif" font-size="12" fill="{color}">{name}</text>'
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_outputs(
    out: Path,
    results: list[SimResult],
    stats: dict[str, WindowStats],
    audit: dict,
    limitations: list[str],
    *,
    headline: tuple[date, date],
    requested: tuple[date, date],
    post_stats: dict[str, WindowStats],
    names: dict[str, str] | None = None,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    base_names = [name for name in stats if name[:1] in "ABCDE" and name[1] == "_"]
    # Keep A–E in front. Names are A_equal, B_score, C_score_overlay, D_, E_score.
    order = [
        "A_equal_1x",
        "B_score_1x",
        "C_score_overlay_1x",
        "D_score_overlay_1_5x",
        "E_score_overlay_2x",
    ]
    rows = [_stats_row(name, stats[name]) for name in order if name in stats]
    rows += [_stats_row(name, stats[name]) for name in stats if name not in order]
    _write_csv(
        out / "summary.csv",
        rows,
        [
            "strategy",
            "start",
            "end",
            "start_equity",
            "end_equity",
            "total_return",
            "cagr",
            "volatility",
            "sharpe",
            "sortino",
            "max_drawdown",
            "trades",
            "trades_per_year",
            "avg_holdings",
            "avg_holding_days",
            "traded_notional",
            "costs",
            "interest",
            "avg_leverage",
            "max_leverage",
            "max_gross",
            "avg_cash_ratio",
            "min_cash_ratio",
            "avg_semi_weight",
            "avg_elec_weight",
            "avg_top_weight",
            "bench_total_return",
            "bench_cagr",
            "excess_cagr",
            "ruined",
        ],
    )
    yearly_rows = []
    monthly_rows = []
    for row in rows:
        yearly = row["yearly"]
        monthly = row["monthly"]
        assert isinstance(yearly, dict)
        assert isinstance(monthly, dict)
        for year, value in yearly.items():
            yearly_rows.append({"strategy": row["strategy"], "year": year, "return": value})
        for month, value in monthly.items():
            monthly_rows.append({"strategy": row["strategy"], "month": month, "return": value})
    _write_csv(out / "yearly_returns.csv", yearly_rows, ["strategy", "year", "return"])
    _write_csv(out / "monthly_returns.csv", monthly_rows, ["strategy", "month", "return"])

    by_name = {result.spec.name: result for result in results}
    start, end = headline
    equity_lines = ["date," + ",".join(order + ["benchmark_1306"])]
    curves: dict[str, list[float]] = {name: [] for name in order}
    drawdowns: dict[str, list[float]] = {name: [] for name in order}
    bench_curve: list[float] = []
    dates: list[date] = []
    peaks = {name: None for name in order}
    for row in by_name[order[0]].daily:
        if not (start <= row.day <= end):
            continue
        dates.append(row.day)
        cells = [row.day.isoformat()]
        bench = row.benchmark
        for name in order:
            match = next(item for item in by_name[name].daily if item.day == row.day)
            cells.append(f"{match.equity:.2f}")
            base = next(item.equity for item in by_name[name].daily if item.day == dates[0])
            curves[name].append(100.0 * match.equity / base if base else 100.0)
            peaks[name] = match.equity if peaks[name] is None else max(peaks[name], match.equity)
            drawdowns[name].append(match.equity / peaks[name] - 1.0 if peaks[name] else 0.0)
        if bench is not None:
            cells.append(f"{bench:.4f}")
            if not bench_curve:
                bench_base = bench
            bench_curve.append(100.0 * bench / bench_base)
        else:
            cells.append("")
        equity_lines.append(",".join(cells))
    (out / "equity_curves.csv").write_text("\n".join(equity_lines) + "\n", encoding="utf-8")
    if bench_curve:
        curves["1306"] = bench_curve
        drawdowns["1306"] = []
        peak_b = bench_curve[0]
        for value in bench_curve:
            peak_b = max(peak_b, value)
            drawdowns["1306"].append(value / peak_b - 1.0)
    _svg(out / "equity_curves.svg", curves, "Growth of 100, headline window")
    _svg(out / "drawdowns.svg", drawdowns, "Drawdown, headline window")

    contrib_rows = []
    for name in order:
        result = by_name[name]
        ranked = sorted(result.pnl_by_code.items(), key=lambda item: item[1], reverse=True)
        for code, pnl in ranked[:15] + ranked[-10:]:
            contrib_rows.append(
                {
                    "strategy": name,
                    "code": code,
                    "name": result.spec and by_name[name] and "",
                    "pnl": round(pnl, 0),
                }
            )
        # names live on the panel, copied during the run onto pnl only.
    # Recover names from the first result's panel via a side channel: the
    # simulator stores them only if the panel was mutated. Read CoName from
    # the caller's result object by stashing on the function attribute below.
    known = names or {}
    for row in contrib_rows:
        row["name"] = known.get(str(row["code"]), "")
    _write_csv(out / "contributors.csv", contrib_rows, ["strategy", "code", "name", "pnl"])

    payload = {
        "requested": [requested[0].isoformat(), requested[1].isoformat()],
        "headline": [headline[0].isoformat(), headline[1].isoformat()],
        "strategies": rows,
        "post_period": {name: _stats_row(name, item) for name, item in post_stats.items()},
        "audit": audit,
        "limitations": limitations,
        "exits": {name: by_name[name].exits for name in order},
        "delist_exits": {name: by_name[name].delist_exits for name in order},
        "deferred_days": {name: by_name[name].deferred_days for name in order},
        "ruined": {name: by_name[name].ruined for name in order},
        "bench_missing_signals": {name: by_name[name].bench_missing_signals for name in order},
    }
    (out / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _ = base_names
