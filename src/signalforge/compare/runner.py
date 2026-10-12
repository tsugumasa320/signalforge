from __future__ import annotations

import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
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


_METRIC_TOP_KEYS = (
    "profit_factor",
    "gross_profit_factor",
    "win_rate",
    "total_trades",
    "total_return_pct",
    "sharpe",
    "sortino",
    "max_drawdown_pct",
    "total_fees_usd",
    "total_slippage_usd",
    "total_cost_usd",
    "avg_cost_per_trade_usd",
    "avg_hold_bars",
)


def _row_from_pipeline_result(sym: str, result: dict[str, Any]) -> dict[str, Any]:
    """Full metric bundles for experiment JSON; top-level keys for aggregators."""
    m = result.get("metrics") or {}
    row: dict[str, Any] = {
        "ticker": sym,
        "error": None,
        "metrics": m,
        "metrics_oos": result.get("metrics_oos") or {},
        "metrics_in_sample": result.get("metrics_in_sample") or {},
        "backtest_window": result.get("backtest_window"),
        "backtest_start": result.get("backtest_start"),
        "backtest_end": result.get("backtest_end"),
        "cost_model": result.get("cost_model"),
    }
    for key in _METRIC_TOP_KEYS:
        if key in m:
            row[key] = m[key]
    return row


def _backtest_single_ticker(
    *,
    style: str,
    strategy_id: str,
    sym: str,
    cost_model: str,
    refresh: bool,
    cfg_override: dict[str, Any] | None,
    bulk_mode: bool = False,
) -> dict[str, Any]:
    try:
        sym_override = {**(cfg_override or {}), "ticker": sym}
        result = run_backtest_pipeline(
            style,
            strategy_id,
            refresh_data=refresh,
            cost_model=cost_model,
            cfg_override=sym_override,
            persist_journal=not bulk_mode,
            slim_return=bulk_mode,
        )
        return _row_from_pipeline_result(sym, result)
    except Exception as exc:
        return {"ticker": sym, "error": str(exc)}


def run_cohort_backtests(
    *,
    strategy_id: str,
    style: str,
    tickers: list[str],
    cost_model: str,
    refresh: bool,
    cfg_override: dict[str, Any] | None = None,
    ticker_progress_cb=None,
    ticker_progress_every: int = 100,
    max_workers: int = 1,
    after_ticker_cb=None,
    checkpoint_cb=None,
    existing_rows: dict[str, dict[str, Any]] | None = None,
    bulk_mode: bool = True,
) -> dict[str, Any]:
    """Backtest every ticker in the list (no sampling). existing_rows = resume map."""
    by_sym: dict[str, dict[str, Any]] = dict(existing_rows or {})
    pending = [s for s in tickers if s not in by_sym]
    total = len(tickers)

    def _one(sym: str) -> dict[str, Any]:
        row = _backtest_single_ticker(
            style=style,
            strategy_id=strategy_id,
            sym=sym,
            cost_model=cost_model,
            refresh=refresh,
            cfg_override=cfg_override,
            bulk_mode=bulk_mode,
        )
        if after_ticker_cb:
            after_ticker_cb()
        return row

    if max_workers <= 1:
        for i, sym in enumerate(pending, start=len(by_sym)):
            if ticker_progress_cb and i > 0 and i % ticker_progress_every == 0:
                ticker_progress_cb(i, total, sym)
            by_sym[sym] = _one(sym)
            if checkpoint_cb:
                checkpoint_cb(by_sym)
    else:
        completed = len(by_sym)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(_one, sym): sym for sym in pending}
            for fut in as_completed(futs):
                sym = futs[fut]
                by_sym[sym] = fut.result()
                completed += 1
                if checkpoint_cb:
                    checkpoint_cb(by_sym)
                if ticker_progress_cb and completed % ticker_progress_every == 0:
                    ticker_progress_cb(completed, total, sym)

    ticker_rows = [by_sym[s] for s in tickers if s in by_sym]
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
    max_workers: int = 1,
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
                max_workers=max_workers,
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


def default_universe_tickers(ticker_limit: int = 0, *, refresh_listing: bool = False) -> list[str]:
    """All TSE domestic listed equities (JPX official list, ~3,800)."""
    from signalforge.universe.tse_listing import list_tse_tickers

    return list_tse_tickers(refresh=refresh_listing, ticker_limit=ticker_limit)


def catalog_rows_from_compare_matrix(cmp: dict[str, Any]) -> list[dict[str, Any]]:
    """Build per-strategy catalog rows by pooling all cohort ticker backtests."""
    by_strategy: dict[str, list[dict[str, Any]]] = {}
    styles: dict[str, str] = {}
    for cell in cmp.get("cells") or []:
        sid = cell.get("strategy")
        if not sid:
            continue
        styles[sid] = cell.get("style") or styles.get(sid, "swing")
        by_strategy.setdefault(sid, []).extend(cell.get("tickers") or [])

    rows: list[dict[str, Any]] = []
    for sid, ticker_rows in sorted(by_strategy.items()):
        ok = [r for r in ticker_rows if not r.get("error")]
        s = _aggregate(ok)
        rows.append(
            {
                "id": sid,
                "style": styles.get(sid, "swing"),
                "ticker": f"{int(s.get('n_tickers') or 0)}銘柄",
                "n_tickers": s.get("n_tickers"),
                "profit_factor": s.get("median_profit_factor"),
                "mean_profit_factor": s.get("mean_profit_factor"),
                "win_rate": s.get("median_win_rate"),
                "total_trades": s.get("median_trades"),
                "total_return_pct": s.get("mean_return_pct"),
                "pct_pf_above_1": s.get("pct_pf_above_1"),
                "evaluation": "multi_ticker_median",
                "error": None,
            }
        )
    return rows


def build_universe_catalog_rows(
    *,
    strategy_ids: list[str],
    tickers: list[str],
    cost_model: str,
    catalog_by_id: dict[str, dict],
    refresh: bool = False,
    progress_cb=None,
    max_workers: int = 1,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(strategy_ids)
    for i, sid in enumerate(strategy_ids, 1):
        if progress_cb and i % 5 == 0:
            progress_cb(i, total, sid)
        style = resolve_strategy_style(sid, catalog_by_id)
        try:
            block = run_cohort_backtests(
                strategy_id=sid,
                style=style,
                tickers=tickers,
                cost_model=cost_model,
                refresh=refresh,
                max_workers=max_workers,
            )
            s = block.get("summary") or {}
            rows.append(
                {
                    "id": sid,
                    "style": style,
                    "ticker": f"{len(tickers)}銘柄",
                    "n_tickers": s.get("n_tickers"),
                    "profit_factor": s.get("median_profit_factor"),
                    "mean_profit_factor": s.get("mean_profit_factor"),
                    "win_rate": s.get("median_win_rate"),
                    "total_trades": s.get("median_trades"),
                    "total_return_pct": s.get("mean_return_pct"),
                    "pct_pf_above_1": s.get("pct_pf_above_1"),
                    "evaluation": "multi_ticker_median",
                    "error": None,
                }
            )
        except Exception as exc:
            rows.append({"id": sid, "style": style, "error": str(exc)})
    return rows
