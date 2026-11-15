from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signalforge.ai.paths import paper_dir, published_path

RANK_FIELDS = (
    "rank",
    "ticker",
    "code",
    "name",
    "sector",
    "market",
    "price",
    "ret_1y",
    "ret_3y",
    "ret_20d",
    "ret_60d",
    "excess_1y",
    "vol_1y",
    "mdd_1y",
    "dd_52w",
    "turnover_20d",
    "steady_score",
    "trend_r2",
    "vs_ma25",
    "risk_adj_1y",
    "up_month_ratio",
    "target",
    "earnings_last",
    "earnings_next",
    "earnings_next_days",
    "ex_dividend_date",
    "dividend_yield",
    "event_data",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def slim_rank_row(row: dict[str, Any]) -> dict[str, Any]:
    # Always emit known keys (None when absent) so event enrichment can fill gaps.
    return {k: row.get(k) for k in RANK_FIELDS}


def load_trend_ranking() -> dict[str, Any] | None:
    raw = read_json(published_path("trend_screen_ranking.json"))
    return raw if isinstance(raw, dict) else None


def load_tse_summary() -> dict[str, Any] | None:
    raw = read_json(published_path("tse_strategy_summary.json"))
    return raw if isinstance(raw, dict) else None


def summarize_ranking(raw: dict[str, Any], top: int) -> dict[str, Any]:
    from signalforge.ai.events import enrich_event_rows, event_coverage

    as_of = raw.get("as_of") or raw.get("signal_date")
    ranking = enrich_event_rows(
        [slim_rank_row(r) for r in (raw.get("ranking") or [])[: max(0, top)]],
        as_of=str(as_of) if as_of else None,
    )
    targets = enrich_event_rows(
        [slim_rank_row(r) for r in (raw.get("targets") or [])],
        as_of=str(as_of) if as_of else None,
    )
    return {
        "system_id": raw.get("system_id"),
        "version": raw.get("version"),
        "name": raw.get("name"),
        "as_of": as_of,
        "signal_date": raw.get("signal_date"),
        "rebalance_signal_date": raw.get("rebalance_signal_date"),
        "n_universe": raw.get("n_universe"),
        "n_pass": raw.get("n_pass"),
        "n_target": raw.get("n_target"),
        "warning": raw.get("warning"),
        "targets": targets,
        "ranking_top": ranking,
        "event_coverage": event_coverage(ranking + targets),
    }


def summarize_trend_paper() -> dict[str, Any] | None:
    raw = read_json(paper_dir() / "trend_screen.json")
    if not isinstance(raw, dict):
        return None
    open_book = raw.get("open") or {}
    holdings = []
    for h in open_book.get("holdings") or []:
        holdings.append(
            {
                "ticker": h.get("ticker"),
                "code": h.get("code"),
                "name": h.get("name"),
                "weight": h.get("weight"),
                "entry_price": h.get("entry_price"),
                "mark_price": h.get("mark_price"),
                "return": h.get("return"),
            }
        )
    summary = raw.get("summary") or {}
    live = raw.get("live") or {}
    return {
        "system_id": raw.get("system_id"),
        "version": raw.get("version"),
        "name": raw.get("name"),
        "as_of": raw.get("as_of"),
        "open": bool(open_book.get("open")),
        "signal_date": open_book.get("signal_date"),
        "entry_date": open_book.get("entry_date"),
        "month_net": open_book.get("month_net"),
        "month_bench": open_book.get("month_bench"),
        "month_excess": open_book.get("month_excess"),
        "holdings": holdings,
        "live_total_return": live.get("total_return"),
        "live_bench_total": live.get("bench_total"),
        "live_value_jpy": live.get("value_jpy"),
        "summary": {
            "cagr": summary.get("cagr"),
            "bench_cagr": summary.get("bench_cagr"),
            "mean_excess": summary.get("mean_excess"),
            "max_dd": summary.get("max_dd"),
            "hit_rate": summary.get("hit_rate"),
            "n_months": summary.get("n_months"),
        },
    }


def summarize_diversified_papers(limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(paper_dir().glob("diversified_*.json")):
        raw = read_json(path)
        if not isinstance(raw, dict):
            continue
        sim = raw.get("last_sim") or {}
        fills = sim.get("fills") or []
        recent = []
        for f in fills[-5:]:
            recent.append(
                {
                    "ticker": f.get("ticker"),
                    "entry_time": f.get("entry_time"),
                    "exit_time": f.get("exit_time"),
                    "pnl_pct": f.get("pnl_pct"),
                }
            )
        rows.append(
            {
                "file": path.name,
                "style": raw.get("style"),
                "strategy": raw.get("strategy"),
                "cohort": raw.get("cohort"),
                "last_run_at": raw.get("last_run_at"),
                "initial_capital": raw.get("initial_capital") or sim.get("initial_capital"),
                "final_equity": sim.get("final_equity"),
                "total_return_pct": sim.get("total_return_pct"),
                "max_drawdown_pct": sim.get("max_drawdown_pct"),
                "win_rate_pct": sim.get("win_rate_pct"),
                "accepted_trades": sim.get("accepted_trades"),
                "recent_fills": recent,
            }
        )
    rows.sort(key=lambda r: float(r.get("total_return_pct") or -1e18), reverse=True)
    return rows[: max(0, limit)]


def summarize_tse_strategies(limit: int = 10) -> dict[str, Any] | None:
    raw = load_tse_summary()
    if not raw:
        return None
    rows = []
    for r in (raw.get("rows") or [])[: max(0, limit)]:
        port = r.get("portfolio") or {}
        rows.append(
            {
                "strategy_id": r.get("strategy_id"),
                "style": r.get("style"),
                "expectancy_pct": r.get("expectancy_pct"),
                "profit_factor": r.get("profit_factor"),
                "win_rate": r.get("win_rate"),
                "max_drawdown_pct": r.get("max_drawdown_pct"),
                "portfolio_total_return_pct": port.get("total_return_pct"),
                "portfolio_oos_return_pct": port.get("oos_return_pct"),
                "portfolio_max_drawdown_pct": port.get("max_drawdown_pct"),
            }
        )
    return {
        "generated_at": raw.get("generated_at"),
        "top_rows": rows,
    }


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
