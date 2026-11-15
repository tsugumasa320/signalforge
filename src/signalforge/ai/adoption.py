"""Log AI ADOPT decisions and evaluate forward returns from OHLCV cache."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from signalforge.ai.packet import read_json, utc_now_iso, write_json
from signalforge.ai.paths import published_path
from signalforge.data.cache import ParquetCache

LOG_SCHEMA = "signalforge-ai-adoption-log/v1"
EVAL_SCHEMA = "signalforge-ai-adoption-eval/v1"
DEFAULT_HORIZONS = (5, 20)


def adoption_log_path():
    return published_path("ai_adoption_log.json")


def adoption_eval_path():
    return published_path("ai_adoption_eval.json")


def load_adoption_log() -> dict[str, Any]:
    raw = read_json(adoption_log_path())
    if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
        return raw
    return {"schema": LOG_SCHEMA, "entries": []}


def append_adoptions_from_score(
    score_resp: dict[str, Any],
    *,
    source: str = "rules/v1",
) -> dict[str, Any]:
    """Append one log entry for as_of if not already present."""
    as_of = str(score_resp.get("as_of") or "")
    if not as_of:
        raise ValueError("score response needs as_of")
    log = load_adoption_log()
    entries = list(log.get("entries") or [])
    if any(str(e.get("as_of")) == as_of for e in entries):
        log["updated_at"] = utc_now_iso()
        write_json(adoption_log_path(), log)
        return log

    scores = {str(s.get("ticker")): s for s in (score_resp.get("scores") or []) if s.get("ticker")}
    adopted_tickers = [str(t) for t in (score_resp.get("adopted") or [])]
    if not adopted_tickers:
        adopted_tickers = [
            str(s["ticker"])
            for s in (score_resp.get("scores") or [])
            if s.get("decision") == "ADOPT" and s.get("ticker")
        ]

    adopted_rows = []
    for t in adopted_tickers:
        s = scores.get(t) or {}
        # price may live on ranking candidate; score response may not include it
        price = s.get("price")
        adopted_rows.append(
            {
                "ticker": t,
                "name": s.get("name"),
                "total": s.get("total"),
                "price": price,
                "decision": "ADOPT",
            }
        )

    watched = [
        {
            "ticker": s.get("ticker"),
            "name": s.get("name"),
            "total": s.get("total"),
            "decision": s.get("decision"),
        }
        for s in (score_resp.get("scores") or [])
        if s.get("decision") == "WATCH"
    ]
    skipped = sum(1 for s in (score_resp.get("scores") or []) if s.get("decision") == "SKIP")

    # Fill prices from ranking packet / cache if missing
    from signalforge.ai.packet import load_trend_ranking

    ranking = load_trend_ranking() or {}
    price_map = {
        str(r.get("ticker")): r.get("price")
        for r in (ranking.get("ranking") or [])
        if r.get("ticker")
    }
    for row in adopted_rows:
        if row.get("price") is None:
            row["price"] = price_map.get(row["ticker"])
        if row.get("price") is None:
            row["price"] = _close_on_or_before(row["ticker"], as_of)

    entries.append(
        {
            "as_of": as_of,
            "logged_at": utc_now_iso(),
            "source": source,
            "adopted": adopted_rows,
            "watched": watched,
            "skipped_count": skipped,
        }
    )
    log = {"schema": LOG_SCHEMA, "updated_at": utc_now_iso(), "entries": entries}
    write_json(adoption_log_path(), log)
    return log


def _close_on_or_before(ticker: str, as_of: str) -> float | None:
    cache = ParquetCache()
    df = cache.load(ticker, "1d")
    if df is None or df.empty:
        return None
    close = _close_series(df)
    if close.empty:
        return None
    target = pd.Timestamp(as_of)
    if close.index.tz is not None and target.tzinfo is None:
        target = target.tz_localize("UTC")
    elif close.index.tz is None and target.tzinfo is not None:
        target = target.tz_localize(None)
    hist = close.loc[close.index <= target]
    if hist.empty:
        return None
    return float(hist.iloc[-1])


def _close_series(df: pd.DataFrame) -> pd.Series:
    if "close" in df.columns:
        s = df["close"]
    elif "Close" in df.columns:
        s = df["Close"]
    else:
        return pd.Series(dtype=float)
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index, utc=True)
    return s.dropna().sort_index()


def _forward_return(
    ticker: str,
    as_of: str,
    horizon: int,
    entry_price: float | None,
) -> dict[str, Any]:
    cache = ParquetCache()
    df = cache.load(ticker, "1d")
    if df is None or df.empty:
        return {"status": "missing_data", "ret": None, "price": None}
    close = _close_series(df)
    target = pd.Timestamp(as_of)
    if close.index.tz is not None and target.tzinfo is None:
        target = target.tz_localize("UTC")
    elif close.index.tz is None and target.tzinfo is not None:
        target = target.tz_localize(None)
    # entry = first bar on/after as_of (signal day close), exit = horizon bars later
    future = close.loc[close.index >= target]
    if future.empty:
        return {"status": "pending", "ret": None, "price": None}
    entry = float(entry_price) if entry_price is not None else float(future.iloc[0])
    if len(future) <= horizon:
        return {"status": "pending", "ret": None, "price": None, "entry_price": entry}
    px = float(future.iloc[horizon])
    ret = px / entry - 1.0 if entry else None
    return {"status": "ok", "ret": ret, "price": px, "entry_price": entry}


def _summarize_rows(rows: list[dict[str, Any]], horizons: tuple[int, ...]) -> dict[str, Any]:
    summary: dict[str, Any] = {"n_adopted_rows": len(rows)}
    for h in horizons:
        key = f"ret_{h}d"
        vals = [float(r[key]) for r in rows if r.get(f"status_{h}d") == "ok" and r.get(key) is not None]
        summary[f"n_eval_{h}d"] = len(vals)
        summary[f"mean_ret_{h}d"] = (sum(vals) / len(vals)) if vals else None
        summary[f"hit_rate_{h}d"] = (sum(1 for v in vals if v > 0) / len(vals)) if vals else None
    return summary


def evaluate_adoptions(
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """Forward-return eval for ADOPT proposals + approved-only paper-intent slice."""
    from signalforge.ai.approval import approval_status_map, item_id

    log = load_adoption_log()
    gate_map = approval_status_map()
    rows: list[dict[str, Any]] = []
    for entry in log.get("entries") or []:
        as_of = str(entry.get("as_of") or "")
        for a in entry.get("adopted") or []:
            ticker = str(a.get("ticker") or "")
            if not ticker or not as_of:
                continue
            gate = gate_map.get(item_id(as_of, ticker)) or "ungated"
            base = {
                "as_of": as_of,
                "ticker": ticker,
                "name": a.get("name"),
                "score_total": a.get("total"),
                "entry_price": a.get("price"),
                "gate": gate,
                "paper_intent": gate == "approved",
            }
            for h in horizons:
                fr = _forward_return(ticker, as_of, h, a.get("price"))
                base[f"status_{h}d"] = fr["status"]
                base[f"ret_{h}d"] = fr.get("ret")
                base[f"price_{h}d"] = fr.get("price")
                if fr.get("entry_price") is not None and base.get("entry_price") is None:
                    base["entry_price"] = fr["entry_price"]
            rows.append(base)

    approved_rows = [r for r in rows if r.get("paper_intent")]
    summary = _summarize_rows(rows, horizons)
    summary_approved = _summarize_rows(approved_rows, horizons)
    summary_approved["n_paper_intents"] = len(approved_rows)

    payload = {
        "schema": EVAL_SCHEMA,
        "generated_at": utc_now_iso(),
        "horizons_days": list(horizons),
        "rows": rows,
        "summary": summary,
        "summary_approved": summary_approved,
        "notes": {
            "summary": "all ADOPT proposals (system performance)",
            "summary_approved": "approved gate only (human paper intent; no brokerage)",
        },
    }
    write_json(adoption_eval_path(), payload)
    return payload
