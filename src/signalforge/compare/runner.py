from __future__ import annotations

import statistics
from typing import Any

from signalforge.pipeline import run_backtest_pipeline
from signalforge.universe.filters import get_preset, resolve_cohort_tickers


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n_tickers": 0, "n_ok": 0, "n_err": 0}
    pfs = [float(r["profit_factor"]) for r in rows if r.get("profit_factor") is not None]
    wins = [float(r["win_rate"]) for r in rows if r.get("win_rate") is not None]
    trades = [int(r["total_trades"]) for r in rows if r.get("total_trades") is not None]
    rets = [float(r["total_return_pct"]) for r in rows if r.get("total_return_pct") is not None]
    pf_gt_1 = sum(1 for p in pfs if p > 1.0) / len(pfs) if pfs else 0.0
    return {
        "n_tickers": len(rows),
        "n_ok": sum(1 for r in rows if not r.get("error")),
        "n_err": sum(1 for r in rows if r.get("error")),
        "median_profit_factor": statistics.median(pfs) if pfs else None,
        "mean_profit_factor": statistics.mean(pfs) if pfs else None,
        "pct_pf_above_1": pf_gt_1,
        "median_win_rate": statistics.median(wins) if wins else None,
        "median_trades": statistics.median(trades) if trades else None,
        "mean_return_pct": statistics.mean(rets) if rets else None,
    }


def run_cohort_backtests(
    *,
    strategy_id: str,
    style: str,
    tickers: list[str],
    cost_model: str,
    refresh: bool,
    cfg_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ticker_rows: list[dict[str, Any]] = []
    for sym in tickers:
        try:
            sym_override = {**(cfg_override or {}), "ticker": sym}
            result = run_backtest_pipeline(
                style,
                strategy_id,
                refresh_data=refresh,
                cost_model=cost_model,
                cfg_override=sym_override,
            )
            m = result.get("metrics") or {}
            ticker_rows.append(
                {
                    "ticker": sym,
                    "profit_factor": m.get("profit_factor"),
                    "win_rate": m.get("win_rate"),
                    "total_trades": m.get("total_trades"),
                    "total_return_pct": m.get("total_return_pct"),
                    "error": None,
                }
            )
        except Exception as exc:
            ticker_rows.append({"ticker": sym, "error": str(exc)})
    return {
        "strategy": strategy_id,
        "style": style,
        "tickers": ticker_rows,
        "summary": _aggregate([r for r in ticker_rows if not r.get("error")]),
    }


def resolve_strategy_style(strategy_id: str, catalog_by_id: dict[str, dict]) -> str:
    cat = catalog_by_id.get(strategy_id, {})
    return cat.get("style") or "swing"


def run_comparison_matrix(
    *,
    strategy_ids: list[str],
    cohort_specs: list[tuple[str, str, dict[str, Any]]],
    cost_model: str,
    refresh: bool,
    catalog_by_id: dict[str, dict],
    ticker_limit: int = 0,
    progress_cb=None,
) -> dict[str, Any]:
    """cohort_specs: (cohort_id, label, filter_dict)."""
    matrix: list[dict[str, Any]] = []
    total = len(cohort_specs) * len(strategy_ids)
    done = 0
    for cohort_id, label, filt in cohort_specs:
        tickers = resolve_cohort_tickers(filt)
        if ticker_limit > 0:
            tickers = tickers[:ticker_limit]
        for sid in strategy_ids:
            done += 1
            if progress_cb and done % 10 == 0:
                progress_cb(done, total, sid, cohort_id)
            style = resolve_strategy_style(sid, catalog_by_id)
            block = run_cohort_backtests(
                strategy_id=sid,
                style=style,
                tickers=tickers,
                cost_model=cost_model,
                refresh=refresh,
            )
            matrix.append(
                {
                    "cohort_id": cohort_id,
                    "cohort_label": label,
                    "filter": filt,
                    "n_tickers": len(tickers),
                    **block,
                }
            )
    return {"cells": matrix}


def preset_specs(preset_ids: list[str]) -> list[tuple[str, str, dict[str, Any]]]:
    out: list[tuple[str, str, dict[str, Any]]] = []
    for pid in preset_ids:
        p = get_preset(pid)
        out.append((p["id"], p.get("label", p["id"]), p.get("filter") or {}))
    return out
