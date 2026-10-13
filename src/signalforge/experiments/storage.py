"""Experiment strategy JSON I/O (compact rows, external ticker files)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signalforge.config import data_dir

TICKERS_SUFFIX = ".tickers.json"

# Top-level sidecar keys required for TSE 期待値 / 最大DD 集計
CORE_TICKER_METRIC_KEYS = ("avg_pnl_pct", "max_drawdown_pct")


def _strategies_dir() -> Path:
    d = data_dir() / "reports" / "experiments" / "strategies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tickers_sidecar_name(strategy_id: str) -> str:
    return f"{strategy_id}{TICKERS_SUFFIX}"


def tickers_sidecar_path(strategy_id: str) -> Path:
    return _strategies_dir() / tickers_sidecar_name(strategy_id)


def rows_for_universe_aggregate(rows: list[dict[str, Any]], *, min_valid: int = 1) -> list[dict[str, Any]]:
    """Universe 集計に使う行（旧バグの期待値 -65% 等を除外）。"""
    ok = [r for r in rows if not r.get("error")]
    valid = [r for r in ok if ticker_row_has_core_metrics(r)]
    if len(valid) >= min_valid:
        return valid
    return ok


def ticker_row_has_core_metrics(row: dict[str, Any]) -> bool:
    if row.get("error"):
        return True
    trades = int(row.get("total_trades") or 0)
    if trades <= 0:
        return False
    avg = row.get("avg_pnl_pct")
    dd = row.get("max_drawdown_pct")
    if avg is None or dd is None:
        return False
    # 旧バグ: 部分投入なのに口座全額基準 → 1トレードあたり約 -65% 前後
    if avg <= -20.0:
        return False
    return True


def compact_ticker_row(row: dict[str, Any]) -> dict[str, Any]:
    """Drop redundant nested metric blobs; keep top-level aggregator keys."""
    if row.get("error"):
        return dict(row)
    nested = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    out = {k: v for k, v in row.items() if k not in ("metrics", "metrics_oos", "metrics_in_sample")}
    for key in CORE_TICKER_METRIC_KEYS:
        if out.get(key) is None and nested.get(key) is not None:
            out[key] = nested[key]
    return out


def compact_ticker_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compact_ticker_row(r) for r in rows]


def load_ticker_rows(strategy_id: str, doc: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if doc is None:
        doc = load_strategy_header(strategy_id)
    if not doc:
        return []
    inline = doc.get("tickers")
    if inline:
        return list(inline)
    side = doc.get("tickers_file")
    if side:
        path = _strategies_dir() / side
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []
    path = tickers_sidecar_path(strategy_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def load_strategy_header(strategy_id: str) -> dict[str, Any] | None:
    path = _strategies_dir() / f"{strategy_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def persist_strategy_document(
    strategy_id: str,
    doc: dict[str, Any],
    *,
    split_tickers: bool = True,
    compact: bool = True,
) -> Path:
    """Write main JSON; optionally move tickers to sidecar and compact rows."""
    payload = dict(doc)
    tickers = payload.pop("tickers", None)
    out_path = _strategies_dir() / f"{strategy_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if tickers is not None:
        rows = compact_ticker_rows(tickers) if compact else list(tickers)
        if split_tickers and rows:
            side_path = tickers_sidecar_path(strategy_id)
            side_path.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            payload["tickers_file"] = side_path.name
        else:
            payload["tickers"] = rows

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def compact_strategy_file(path: Path, *, split_tickers: bool = True) -> tuple[int, int]:
    """Compact one strategy JSON in place. Returns (n_tickers, bytes_saved_estimate)."""
    before = path.stat().st_size
    doc = json.loads(path.read_text(encoding="utf-8"))
    sid = str(doc.get("strategy_id") or path.stem)
    tickers = load_ticker_rows(sid, doc)
    if not tickers and doc.get("tickers"):
        tickers = doc["tickers"]
    doc.pop("tickers", None)
    doc.pop("tickers_file", None)
    if tickers:
        doc["tickers"] = tickers
    persist_strategy_document(sid, doc, split_tickers=split_tickers, compact=True)
    after = path.stat().st_size
    side = tickers_sidecar_path(sid)
    total_after = after + (side.stat().st_size if side.exists() else 0)
    saved = max(0, before - total_after)
    return len(tickers), saved
