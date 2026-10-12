"""One pass per strategy × all TSE tickers → segment / sector / universe aggregates."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from signalforge.compare.runner import _aggregate, resolve_strategy_style, run_cohort_backtests
from signalforge.config import CONFIG_DIR, data_dir, load_yaml
from signalforge.experiments.schedule import ExecutionBudget
from signalforge.universe.tse_listing import listing_by_ticker, list_tse_tickers


def experiments_dir() -> Path:
    p = data_dir() / "reports" / "experiments"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_plan() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "experiments" / "backtest_plan.yaml")


def _checkpoint_path(strategy_id: str) -> Path:
    return experiments_dir() / "strategies" / f"{strategy_id}.checkpoint.json"


def _strategy_path(strategy_id: str) -> Path:
    return experiments_dir() / "strategies" / f"{strategy_id}.json"


def _load_checkpoint(strategy_id: str) -> dict[str, Any]:
    path = _checkpoint_path(strategy_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_checkpoint(strategy_id: str, payload: dict[str, Any]) -> None:
    path = _checkpoint_path(strategy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_complete(doc: dict[str, Any], n_target: int) -> bool:
    return bool(doc.get("complete")) and int(doc.get("n_tickers_target") or 0) == n_target


def _rows_to_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(r["ticker"]): r for r in rows if r.get("ticker")}


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
) -> dict[str, Any]:
    ok = [r for r in enriched if not r.get("error")]
    complete = len(enriched) >= len(tickers)
    return {
        "strategy_id": strategy_id,
        "style": style,
        "n_tickers_target": len(tickers),
        "n_tickers_done": len(enriched),
        "complete": complete,
        "tickers": enriched,
        "universe": _aggregate(ok),
        "by_segment": _aggregate_group(ok, "segment"),
        "by_sector": _aggregate_group(ok, "sector_tse"),
    }


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
) -> dict[str, Any]:
    style = resolve_strategy_style(strategy_id, catalog_by_id)
    existing: dict[str, dict[str, Any]] = {}
    if resume:
        ck = _load_checkpoint(strategy_id)
        if ck.get("tickers"):
            existing = _rows_to_map(ck["tickers"])
        final_path = _strategy_path(strategy_id)
        if final_path.exists():
            doc = json.loads(final_path.read_text(encoding="utf-8"))
            if _is_complete(doc, len(tickers)):
                return doc
            if doc.get("tickers"):
                existing = {**existing, **_rows_to_map(doc["tickers"])}

    def _after_ticker() -> None:
        budget.sleep_after_ticker()

    def _checkpoint(by_sym: dict[str, dict[str, Any]]) -> None:
        rows = [by_sym[s] for s in tickers if s in by_sym]
        if not rows:
            return
        enriched = _enrich_ticker_rows(rows, meta)
        _save_checkpoint(
            strategy_id,
            {
                "strategy_id": strategy_id,
                "tickers": enriched,
                "n_tickers_target": len(tickers),
                "n_tickers_done": len(enriched),
            },
        )

    block = run_cohort_backtests(
        strategy_id=strategy_id,
        style=style,
        tickers=tickers,
        cost_model=cost_model,
        refresh=False,
        ticker_progress_cb=ticker_progress_cb,
        ticker_progress_every=budget.ticker_progress_every,
        max_workers=budget.parallel_workers,
        after_ticker_cb=_after_ticker,
        checkpoint_cb=_checkpoint,
        existing_rows=existing,
    )
    enriched = _enrich_ticker_rows(block.get("tickers") or [], meta)
    doc = _finalize_strategy_doc(strategy_id, style, tickers, enriched)

    out_path = _strategy_path(strategy_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if doc.get("complete"):
        ck_path = _checkpoint_path(strategy_id)
        if ck_path.exists():
            ck_path.unlink()
    else:
        _save_checkpoint(strategy_id, {"tickers": enriched, "n_tickers_target": len(tickers)})
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
) -> dict[str, Any]:
    started = datetime.now(timezone.utc).astimezone().isoformat()
    budget = budget or ExecutionBudget.from_config()
    meta = listing_by_ticker()
    tickers = list_tse_tickers()
    if ticker_limit > 0:
        tickers = tickers[:ticker_limit]
    elif budget.max_tickers_per_strategy > 0:
        tickers = tickers[: budget.max_tickers_per_strategy]

    out_dir = experiments_dir() / "strategies"
    out_dir.mkdir(parents=True, exist_ok=True)

    done = skipped = failed = stopped = processed_new = 0
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
        if resume and final_path.exists():
            try:
                doc = json.loads(final_path.read_text(encoding="utf-8"))
                if _is_complete(doc, len(tickers)):
                    skipped += 1
                    if progress_cb:
                        progress_cb(i, total, f"{sid} (完了済み)")
                    continue
            except json.JSONDecodeError:
                pass

        if progress_cb:
            progress_cb(i, total, sid)
        try:
            run_strategy_pass(
                sid,
                tickers=tickers,
                catalog_by_id=catalog_by_id,
                cost_model=cost_model,
                meta=meta,
                budget=budget,
                ticker_progress_cb=ticker_progress_cb,
                resume=resume,
            )
            processed_new += 1
            done += 1
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
        "note": "skipped_complete = 全銘柄済み。省略ではなく再計算不要。",
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


def build_experiment_summaries(strategy_ids: list[str], *, tickers_count: int) -> dict[str, Any]:
    """Roll up per-strategy JSON into segment / sector matrices."""
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
                "median_pf": u.get("median_profit_factor"),
                "mean_pf": u.get("mean_profit_factor"),
                "n_tickers": u.get("n_tickers"),
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

    universe_rows.sort(key=lambda x: float(x.get("median_pf") or 0), reverse=True)
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
    return min(8, max(1, (os.cpu_count() or 4)))
