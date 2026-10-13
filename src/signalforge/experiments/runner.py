"""One pass per strategy × all TSE tickers → segment / sector / universe aggregates."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from signalforge.backtest.capital import (
    backtest_capital_record,
    capital_records_match,
    pipeline_cfg_override_from_capital,
    resolve_experiment_capital,
)
from signalforge.compare.runner import _aggregate, resolve_strategy_style, run_cohort_backtests
from signalforge.config import CONFIG_DIR, data_dir, load_yaml
from signalforge.experiments.schedule import ExecutionBudget
from signalforge.experiments.series import SERIES_SCHEMA, ticker_row_has_series
from signalforge.experiments.storage import (
    load_strategy_header,
    load_ticker_rows,
    persist_strategy_document,
    rows_for_universe_aggregate,
    ticker_row_has_core_metrics,
)
from signalforge.universe.tse_listing import listing_by_ticker, list_tse_tickers


def experiments_dir() -> Path:
    p = data_dir() / "reports" / "experiments"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_plan() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "experiments" / "backtest_plan.yaml")


def _checkpoint_path(strategy_id: str) -> Path:
    return experiments_dir() / "strategies" / f"{strategy_id}.checkpoint.json"


def _checkpoint_tickers_path(strategy_id: str) -> Path:
    return experiments_dir() / "strategies" / f"{strategy_id}.checkpoint.tickers.json"


def _strategy_path(strategy_id: str) -> Path:
    return experiments_dir() / "strategies" / f"{strategy_id}.json"


def _load_checkpoint(strategy_id: str) -> dict[str, Any]:
    path = _checkpoint_path(strategy_id)
    if not path.exists():
        return {}
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(meta, dict):
        return {}
    side = _checkpoint_tickers_path(strategy_id)
    if side.exists():
        try:
            rows = json.loads(side.read_text(encoding="utf-8"))
            if isinstance(rows, list):
                meta["tickers"] = rows
        except json.JSONDecodeError:
            pass
    return meta


def _save_checkpoint(strategy_id: str, payload: dict[str, Any]) -> None:
    path = _checkpoint_path(strategy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tickers = payload.pop("tickers", None)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if tickers is not None:
        _checkpoint_tickers_path(strategy_id).write_text(
            json.dumps(tickers, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )


def _is_complete(doc: dict[str, Any], n_target: int) -> bool:
    return bool(doc.get("complete")) and int(doc.get("n_tickers_target") or 0) == n_target


def _rows_to_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(r["ticker"]): r for r in rows if r.get("ticker")}


def _resume_rows_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Keep checkpoint rows that already have 期待値・最大DD (re-BT the rest)."""
    return {
        str(r["ticker"]): r
        for r in rows
        if r.get("ticker") and ticker_row_has_core_metrics(r)
    }


def _enrich_ticker_rows(rows: list[dict[str, Any]], meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        sym = r.get("ticker")
        m = meta.get(sym) or {}
        out.append(
            {
                **r,
                "segment": m.get("segment"),
                "sector_tse": m.get("sector_tse"),
                "name": m.get("name"),
            }
        )
    return out


def _aggregate_group(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("error"):
            continue
        g = r.get(key)
        if not g:
            continue
        groups.setdefault(str(g), []).append(r)
    return {g: _aggregate(rs) for g, rs in groups.items()}


def _finalize_strategy_doc(
    strategy_id: str,
    style: str,
    tickers: list[str],
    enriched: list[dict[str, Any]],
    *,
    backtest_capital: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ok = [r for r in enriched if not r.get("error")]
    agg_rows = rows_for_universe_aggregate(ok)
    complete = len(enriched) >= len(tickers)
    doc: dict[str, Any] = {
        "strategy_id": strategy_id,
        "style": style,
        "n_tickers_target": len(tickers),
        "n_tickers_done": len(enriched),
        "complete": complete,
        "universe": _aggregate(agg_rows),
        "by_segment": _aggregate_group(agg_rows, "segment"),
        "by_sector": _aggregate_group(agg_rows, "sector_tse"),
    }
    if backtest_capital:
        doc["backtest_capital"] = backtest_capital
    doc["metrics_schema"] = {"pnl_basis": PNL_METRICS_SCHEMA}
    return doc


def clear_strategy_checkpoints(strategy_id: str) -> None:
    _checkpoint_path(strategy_id).unlink(missing_ok=True)
    _checkpoint_tickers_path(strategy_id).unlink(missing_ok=True)


PNL_METRICS_SCHEMA = "entry_cost_v3"


def strategy_needs_metric_refresh(strategy_id: str) -> bool:
    """True if completed strategy sidecar lacks avg_pnl_pct / max_drawdown_pct."""
    doc = load_strategy_header(strategy_id)
    if not doc or not doc.get("complete"):
        return False
    schema = doc.get("metrics_schema") or {}
    if schema.get("pnl_basis") != PNL_METRICS_SCHEMA:
        return True
    rows = [r for r in load_ticker_rows(strategy_id, doc) if not r.get("error")]
    if not rows:
        return True
    if any(not ticker_row_has_core_metrics(r) for r in rows[: min(50, len(rows))]):
        return True
    sample = rows[0]
    return sample.get("avg_pnl_pct") is None or sample.get("max_drawdown_pct") is None


def list_strategies_needing_metric_refresh(strategy_ids: list[str]) -> list[str]:
    return [sid for sid in strategy_ids if strategy_needs_metric_refresh(sid)]


def strategy_needs_series_refresh(strategy_id: str) -> bool:
    """True if completed strategy lacks trades_compact / equity_daily for period slicing."""
    doc = load_strategy_header(strategy_id)
    if not doc or not doc.get("complete"):
        return False
    if doc.get("series_schema") != SERIES_SCHEMA:
        pass
    rows = [r for r in load_ticker_rows(strategy_id, doc) if not r.get("error")]
    if not rows:
        return True
    sample = rows[: min(50, len(rows))]
    return any(not ticker_row_has_series(r) for r in sample)


def list_strategies_needing_series_refresh(strategy_ids: list[str]) -> list[str]:
    return [sid for sid in strategy_ids if strategy_needs_series_refresh(sid)]


def strategy_needs_capital_refresh(
    strategy_id: str,
    current_capital: dict[str, Any],
    *,
    doc: dict[str, Any] | None = None,
) -> bool:
    if doc is None:
        doc = load_strategy_header(strategy_id) or {}
    if not doc or not doc.get("complete"):
        return False
    stored = doc.get("backtest_capital")
    if not isinstance(stored, dict):
        return True
    return not capital_records_match(stored, current_capital)


def list_strategies_needing_capital_refresh(
    strategy_ids: list[str],
    current_capital: dict[str, Any],
) -> list[str]:
    return [
        sid
        for sid in strategy_ids
        if strategy_needs_capital_refresh(sid, current_capital)
    ]


def resolve_campaign_backtest_capital(
    plan: dict[str, Any] | None = None,
    *,
    initial_cash_jpy: float | None = None,
    max_position_pct: float | None = None,
    min_cash_reserve_pct: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = plan or load_plan()
    plan_cap = (plan.get("meta") or {}).get("backtest_capital")
    policy = resolve_experiment_capital(
        plan_capital=plan_cap if isinstance(plan_cap, dict) else None,
        initial_cash_jpy=initial_cash_jpy,
        max_position_pct=max_position_pct,
        min_cash_reserve_pct=min_cash_reserve_pct,
    )
    record = backtest_capital_record(policy)
    cfg_override = pipeline_cfg_override_from_capital(policy)
    return record, cfg_override


def run_strategy_pass(
    strategy_id: str,
    *,
    tickers: list[str],
    catalog_by_id: dict[str, dict],
    cost_model: str,
    meta: dict[str, dict[str, Any]],
    budget: ExecutionBudget,
    ticker_progress_cb=None,
    resume: bool = True,
    force_redo: bool = False,
    upgrade_incomplete_metrics: bool = False,
    upgrade_incomplete_series: bool = False,
    cfg_override: dict[str, Any] | None = None,
    backtest_capital: dict[str, Any] | None = None,
) -> dict[str, Any]:
    style = resolve_strategy_style(strategy_id, catalog_by_id)
    existing: dict[str, dict[str, Any]] = {}
    if force_redo:
        clear_strategy_checkpoints(strategy_id)
    elif resume or upgrade_incomplete_metrics or upgrade_incomplete_series:
        ck = _load_checkpoint(strategy_id)
        if ck.get("tickers"):
            existing = _resume_rows_map(ck["tickers"])
        final_path = _strategy_path(strategy_id)
        if final_path.exists():
            doc = json.loads(final_path.read_text(encoding="utf-8"))
            complete = _is_complete(doc, len(tickers))
            if (
                complete
                and resume
                and not upgrade_incomplete_metrics
                and not upgrade_incomplete_series
            ):
                return doc
            resume_rows = load_ticker_rows(strategy_id, doc)
            if resume_rows:
                existing = {**existing, **_resume_rows_map(resume_rows)}

    if upgrade_incomplete_metrics and existing:
        # 旧 sidecar（期待値 ≈ -65% 等）はそのまま載せると pending が空になり再BTされない
        existing = {
            sym: row
            for sym, row in existing.items()
            if ticker_row_has_core_metrics(row)
        }

    if upgrade_incomplete_series and existing:
        existing = {
            sym: row for sym, row in existing.items() if ticker_row_has_series(row)
        }

    def _after_ticker() -> None:
        budget.sleep_after_ticker()

    ck_every = max(1, int(budget.checkpoint_every or 1))
    last_ck_n = [0]

    def _checkpoint(by_sym: dict[str, dict[str, Any]]) -> None:
        n = len(by_sym)
        if n < len(tickers) and ck_every > 1 and (n - last_ck_n[0]) < ck_every:
            return
        last_ck_n[0] = n
        rows = [by_sym[s] for s in tickers if s in by_sym]
        if not rows:
            return
        enriched = _enrich_ticker_rows(rows, meta)
        _save_checkpoint(
            strategy_id,
            {
                "strategy_id": strategy_id,
                "n_tickers_target": len(tickers),
                "n_tickers_done": len(enriched),
                "tickers": enriched,
            },
        )

    block = run_cohort_backtests(
        strategy_id=strategy_id,
        style=style,
        tickers=tickers,
        cost_model=cost_model,
        refresh=False,
        cfg_override=cfg_override,
        ticker_progress_cb=ticker_progress_cb,
        ticker_progress_every=budget.ticker_progress_every,
        max_workers=budget.parallel_workers,
        after_ticker_cb=_after_ticker,
        checkpoint_cb=_checkpoint,
        existing_rows=existing,
    )
    enriched = _enrich_ticker_rows(block.get("tickers") or [], meta)
    doc = _finalize_strategy_doc(
        strategy_id,
        style,
        tickers,
        enriched,
        backtest_capital=backtest_capital,
    )
    if any(ticker_row_has_series(r) for r in enriched if not r.get("error")):
        doc["series_schema"] = SERIES_SCHEMA
    doc["tickers"] = enriched
    persist_strategy_document(strategy_id, doc, split_tickers=bool(enriched), compact=True)
    if doc.get("complete"):
        _checkpoint_path(strategy_id).unlink(missing_ok=True)
        _checkpoint_tickers_path(strategy_id).unlink(missing_ok=True)
    else:
        _save_checkpoint(
            strategy_id,
            {
                "strategy_id": strategy_id,
                "n_tickers_target": len(tickers),
                "n_tickers_done": len(enriched),
                "tickers": enriched,
            },
        )
    return doc


def run_experiment_campaign(
    strategy_ids: list[str],
    *,
    ticker_limit: int = 0,
    cost_model: str = "japan",
    catalog_by_id: dict[str, dict],
    resume: bool = True,
    budget: ExecutionBudget | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
    ticker_progress_cb: Callable[[int, int, str], None] | None = None,
    aggregate_every: int = 5,
    refresh_metrics: bool = False,
    refresh_series: bool = False,
    refresh_capital: bool = False,
    initial_cash_jpy: float | None = None,
    max_position_pct: float | None = None,
    min_cash_reserve_pct: float | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc).astimezone().isoformat()
    budget = budget or ExecutionBudget.from_config()
    backtest_capital, cfg_override = resolve_campaign_backtest_capital(
        plan,
        initial_cash_jpy=initial_cash_jpy,
        max_position_pct=max_position_pct,
        min_cash_reserve_pct=min_cash_reserve_pct,
    )
    meta = listing_by_ticker()
    tickers = list_tse_tickers()
    if ticker_limit > 0:
        tickers = tickers[:ticker_limit]
    elif budget.max_tickers_per_strategy > 0:
        tickers = tickers[: budget.max_tickers_per_strategy]

    out_dir = experiments_dir() / "strategies"
    out_dir.mkdir(parents=True, exist_ok=True)

    done = skipped = failed = stopped = processed_new = refreshed = refreshed_series = refreshed_capital = 0
    total = len(strategy_ids)

    for i, sid in enumerate(strategy_ids, 1):
        if budget.time_exhausted():
            stopped = total - (done + skipped + failed)
            if progress_cb:
                progress_cb(i, total, "(時間上限 — 再実行で続き)")
            break
        if not budget.strategies_budget_remaining(processed_new):
            stopped = total - (done + skipped + failed)
            break

        final_path = _strategy_path(sid)
        force_redo = False
        redo_metrics = redo_series = redo_capital = False
        if final_path.exists():
            try:
                doc = json.loads(final_path.read_text(encoding="utf-8"))
                if _is_complete(doc, len(tickers)):
                    if refresh_capital and strategy_needs_capital_refresh(
                        sid, backtest_capital, doc=doc
                    ):
                        force_redo = True
                        redo_capital = True
                    elif refresh_metrics and strategy_needs_metric_refresh(sid):
                        redo_metrics = True
                    elif refresh_series and strategy_needs_series_refresh(sid):
                        redo_series = True
                    if not force_redo and not redo_metrics and not redo_series and resume:
                        skipped += 1
                        if progress_cb:
                            progress_cb(i, total, f"{sid} (完了済み)")
                        continue
            except json.JSONDecodeError:
                pass

        if progress_cb:
            if force_redo and redo_capital:
                tag = f"{sid} (資金条件の再BT)"
            elif redo_metrics and not force_redo:
                tag = f"{sid} (期待値・DD 差し替え)"
            elif redo_series and not force_redo:
                tag = f"{sid} (トレード系列 追記)"
            elif force_redo:
                tag = f"{sid} (再BT)"
            else:
                tag = sid
            progress_cb(i, total, tag)
        try:
            run_strategy_pass(
                sid,
                tickers=tickers,
                catalog_by_id=catalog_by_id,
                cost_model=cost_model,
                meta=meta,
                budget=budget,
                ticker_progress_cb=ticker_progress_cb,
                resume=resume and not force_redo,
                force_redo=force_redo,
                upgrade_incomplete_metrics=redo_metrics and not force_redo,
                upgrade_incomplete_series=redo_series and not force_redo,
                cfg_override=cfg_override,
                backtest_capital=backtest_capital,
            )
            processed_new += 1
            done += 1
            if redo_capital:
                refreshed_capital += 1
            if redo_metrics:
                refreshed += 1
            if redo_series:
                refreshed_series += 1
            budget.sleep_after_strategy()
            if aggregate_every > 0 and done % aggregate_every == 0:
                build_experiment_summaries(strategy_ids, tickers_count=len(tickers))
        except Exception as exc:
            _strategy_path(sid).write_text(
                json.dumps({"strategy_id": sid, "error": str(exc), "complete": False}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            failed += 1

    summary = build_experiment_summaries(strategy_ids, tickers_count=len(tickers))
    finished = datetime.now(timezone.utc).astimezone().isoformat()
    manifest = {
        "plan": "config/experiments/backtest_plan.yaml",
        "schedule": "config/experiments/schedule.yaml",
        "execution": budget.to_manifest_fragment(),
        "started_at": started,
        "finished_at": finished,
        "n_tickers": len(tickers),
        "n_strategies": len(strategy_ids),
        "completed": done,
        "skipped_complete": skipped,
        "failed": failed,
        "stopped_early": stopped,
        "refreshed_metrics": refreshed,
        "refreshed_series": refreshed_series,
        "refreshed_capital": refreshed_capital,
        "backtest_capital": backtest_capital,
        "note": "skipped_complete = 全銘柄済み。--refresh-metrics / --refresh-series / --refresh-capital で完了分を再BT。",
    }
    (experiments_dir() / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary["manifest"] = manifest
    (experiments_dir() / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def refresh_completed_strategy_aggregates(strategy_ids: list[str] | None = None) -> int:
    """Recompute universe / segment / sector from ticker sidecars (no re-backtest)."""
    strat_dir = experiments_dir() / "strategies"
    if strategy_ids is None:
        strategy_ids = sorted(
            p.stem
            for p in strat_dir.glob("*.json")
            if not p.name.endswith(".checkpoint.json") and not p.name.endswith(".tickers.json")
        )
    updated = 0
    for sid in strategy_ids:
        path = strat_dir / f"{sid}.json"
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if doc.get("error") or not doc.get("complete"):
            continue
        rows = load_ticker_rows(sid, doc)
        if not rows:
            continue
        ok = [r for r in rows if not r.get("error")]
        agg_rows = rows_for_universe_aggregate(ok)
        doc["universe"] = _aggregate(agg_rows)
        doc["by_segment"] = _aggregate_group(agg_rows, "segment")
        doc["by_sector"] = _aggregate_group(agg_rows, "sector_tse")
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        updated += 1
    return updated


def build_experiment_summaries(strategy_ids: list[str], *, tickers_count: int) -> dict[str, Any]:
    """Roll up per-strategy JSON into segment / sector matrices."""
    refresh_completed_strategy_aggregates(strategy_ids)
    seg_matrix: list[dict[str, Any]] = []
    sec_matrix: list[dict[str, Any]] = []
    universe_rows: list[dict[str, Any]] = []

    strat_dir = experiments_dir() / "strategies"
    for sid in strategy_ids:
        path = strat_dir / f"{sid}.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("error") or not doc.get("complete"):
            continue
        u = doc.get("universe") or {}
        universe_rows.append(
            {
                "strategy": sid,
                "median_return_pct": u.get("median_total_return_pct"),
                "mean_return_pct": u.get("mean_return_pct"),
                "median_pf": u.get("median_profit_factor"),
                "mean_pf": u.get("mean_profit_factor"),
                "median_trades": u.get("median_trades"),
                "n_tickers": u.get("n_tickers"),
                "pct_return_gt_0": u.get("pct_return_above_0"),
                "pct_pf_gt_1": u.get("pct_pf_above_1"),
            }
        )
        for seg, s in (doc.get("by_segment") or {}).items():
            seg_matrix.append(
                {
                    "strategy": sid,
                    "segment": seg,
                    "median_pf": s.get("median_profit_factor"),
                    "n_tickers": s.get("n_tickers"),
                    "pct_pf_gt_1": s.get("pct_pf_above_1"),
                }
            )
        for sec, s in (doc.get("by_sector") or {}).items():
            sec_matrix.append(
                {
                    "strategy": sid,
                    "sector_tse": sec,
                    "median_pf": s.get("median_profit_factor"),
                    "n_tickers": s.get("n_tickers"),
                }
            )

    universe_rows.sort(key=lambda x: float(x.get("median_return_pct") or 0), reverse=True)
    out = {
        "universe_ranking": universe_rows,
        "n_tickers_pool": tickers_count,
        "n_strategies_complete": len(universe_rows),
    }
    (experiments_dir() / "matrix_segment.json").write_text(
        json.dumps({"cells": seg_matrix}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (experiments_dir() / "matrix_sector.json").write_text(
        json.dumps({"cells": sec_matrix}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    catalog = {
        "meta": {
            "evaluation": "multi_ticker_median",
            "n_tickers": tickers_count,
            "source": "experiments_campaign",
            "complete_only": True,
        },
        "results": [
            {
                "id": r["strategy"],
                "ticker": f"{tickers_count}銘柄",
                "n_tickers": r.get("n_tickers"),
                "profit_factor": r.get("median_pf"),
                "mean_profit_factor": r.get("mean_pf"),
                "total_return_pct": r.get("median_return_pct"),
                "mean_return_pct": r.get("mean_return_pct"),
                "pct_pf_above_1": r.get("pct_pf_gt_1"),
                "evaluation": "multi_ticker_median",
            }
            for r in universe_rows
        ],
    }
    (data_dir() / "reports" / "catalog_backtests.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def default_parallel_workers(override: int = 0) -> int:
    if override > 0:
        return override
    budget = ExecutionBudget.from_config()
    if budget.parallel_workers > 0:
        return budget.parallel_workers
    return min(8, max(1, os.cpu_count() or 4))
