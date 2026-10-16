"""Ticker priority scores for portfolio entry queue (non-lookahead)."""

from __future__ import annotations

from functools import lru_cache

from signalforge.universe.filters import load_equity_meta


@lru_cache(maxsize=1)
def ticker_liquidity_score_map() -> dict[str, float]:
    """Higher = prefer when entry slots compete (liquid / prime / Nikkei)."""
    meta = load_equity_meta().get("tickers") or {}
    out: dict[str, float] = {}
    for sym, m in meta.items():
        score = 0.0
        tags = set(m.get("tags") or [])
        if "japan_liquid" in tags:
            score += 2.0
        if "nikkei225" in tags:
            score += 1.0
        if m.get("segment") == "prime":
            score += 0.5
        out[str(sym)] = score
    return out


@lru_cache(maxsize=1)
def ticker_sector_map() -> dict[str, str]:
    """TSE 33-sector per ticker (full listing, falling back to equity meta)."""
    from signalforge.universe.tse_listing import listing_by_ticker

    meta = load_equity_meta().get("tickers") or {}
    out = {str(sym): str(m.get("sector_tse") or "") for sym, m in meta.items()}
    try:
        listing = listing_by_ticker()
    except Exception:
        listing = {}
    for sym, row in listing.items():
        if row.get("sector_tse"):
            out[str(sym)] = str(row["sector_tse"])
    return out
