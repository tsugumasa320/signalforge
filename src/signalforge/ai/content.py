"""Surprise + news enrichment for AI Score / Brief (cache-first, optional fetch)."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from signalforge.alt_data.paths import alt_data_root
from signalforge.config import data_dir

NEG_NEWS_KW = ("下方修正", "減益", "赤字", "最終赤字", "訴訟", "不正", "減配", "上場廃止", "業績悪化")
POS_NEWS_KW = ("上方修正", "増益", "最高益", "増配", "過去最高", "通期上方", "営業増益")


def ticker_to_jq_code(ticker: str) -> str:
    base = str(ticker).upper().replace(".T", "").strip()
    if base.isdigit() and len(base) == 4:
        return base + "0"
    return base


def news_path(ticker: str) -> Path:
    safe = str(ticker).replace("/", "_")
    d = alt_data_root() / "news"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def fins_parquet_path(code: str) -> Path:
    return data_dir() / "earnings_surprise" / "fins" / f"{code}.parquet"


def load_news(ticker: str, *, limit: int = 3) -> list[dict[str, Any]]:
    path = news_path(ticker)
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = doc.get("items") or []
    out = []
    for it in items[:limit]:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        out.append(
            {
                "title": title[:180],
                "publisher": it.get("publisher"),
                "link": it.get("link"),
                "published_at": it.get("published_at"),
            }
        )
    return out


def save_news(ticker: str, items: list[dict[str, Any]]) -> Path:
    path = news_path(ticker)
    payload = {
        "ticker": ticker,
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "items": items,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def fetch_news_yfinance(ticker: str, *, limit: int = 5, sleep_s: float = 0.05) -> list[dict[str, Any]]:
    """Best-effort Yahoo headlines. Never raises."""
    try:
        import yfinance as yf

        time.sleep(sleep_s)
        raw = getattr(yf.Ticker(ticker), "news", None) or []
    except Exception:  # noqa: BLE001
        return []
    items: list[dict[str, Any]] = []
    for row in raw:
        content = row.get("content") if isinstance(row, dict) else None
        if isinstance(content, dict):
            title = content.get("title") or content.get("summary")
            pub = (content.get("provider") or {}).get("displayName") if isinstance(content.get("provider"), dict) else None
            link = None
            canon = content.get("canonicalUrl") or {}
            if isinstance(canon, dict):
                link = canon.get("url")
            published = content.get("pubDate") or content.get("displayTime")
        elif isinstance(row, dict):
            title = row.get("title")
            pub = row.get("publisher")
            link = row.get("link")
            published = row.get("providerPublishTime")
            if isinstance(published, (int, float)):
                published = datetime.fromtimestamp(published, tz=timezone.utc).isoformat()
        else:
            continue
        if not title:
            continue
        items.append(
            {
                "title": str(title)[:180],
                "publisher": pub,
                "link": link,
                "published_at": published,
            }
        )
        if len(items) >= limit:
            break
    if items:
        save_news(ticker, items)
    return items[:limit]


def _parse_day(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def load_latest_surprise(ticker: str, *, as_of: str | None = None) -> dict[str, Any] | None:
    """Latest company-forecast / YoY event from earnings_surprise fins cache."""
    code = ticker_to_jq_code(ticker)
    path = fins_parquet_path(code)
    if not path.exists():
        return None
    try:
        import polars as pl

        from signalforge.research.earnings_surprise.events import build_events

        rows = pl.read_parquet(path).to_dicts()
        events = build_events(rows)
    except Exception:  # noqa: BLE001
        return None
    if not events:
        return None
    cutoff = _parse_day(as_of) or date.today()
    past = [e for e in events if e.disc_date and e.disc_date <= cutoff]
    if not past:
        return None
    past.sort(key=lambda e: (e.disc_date, e.disc_time or ""), reverse=True)
    e = past[0]
    days_ago = (cutoff - e.disc_date).days if e.disc_date else None
    summary_bits = []
    if e.c0:
        summary_bits.append("C0該当（会社予想上方 or 増益+利益率改善）")
    if e.rev_op is True:
        summary_bits.append("営業利益会社予想を上方修正")
    if e.rev_op is False:
        summary_bits.append("営業利益会社予想の上方修正なし")
    if e.op_yoy is not None:
        summary_bits.append(f"営業利益YoY {e.op_yoy:+.1%}")
    if not summary_bits:
        summary_bits.append(f"決算発表 {e.period or ''}".strip())
    return {
        "code": e.code,
        "disc_date": e.disc_date.isoformat() if e.disc_date else None,
        "days_ago": days_ago,
        "period": e.period,
        "c0": bool(e.c0),
        "rev_op": e.rev_op,
        "op_yoy": e.op_yoy,
        "opm_delta": e.opm_delta,
        "basis": e.basis,
        "summary": " · ".join(summary_bits),
    }


def news_sentiment(titles: list[str]) -> str:
    blob = " ".join(titles)
    pos = any(k in blob for k in POS_NEWS_KW)
    neg = any(k in blob for k in NEG_NEWS_KW)
    if pos and not neg:
        return "positive"
    if neg and not pos:
        return "negative"
    if pos and neg:
        return "mixed"
    return "neutral"


def enrich_content_fields(
    row: dict[str, Any],
    *,
    as_of: str | None = None,
    fetch_news: bool = False,
) -> dict[str, Any]:
    out = dict(row)
    ticker = out.get("ticker")
    if not ticker:
        out.setdefault("content_data", "missing")
        return out

    surprise = load_latest_surprise(str(ticker), as_of=as_of)
    news = load_news(str(ticker), limit=3)
    if fetch_news and not news:
        news = fetch_news_yfinance(str(ticker), limit=5)

    if surprise:
        out["surprise"] = surprise
    if news:
        out["news"] = news
        out["news_sentiment"] = news_sentiment([str(n.get("title") or "") for n in news])

    if surprise and news:
        out["content_data"] = "both"
    elif surprise:
        out["content_data"] = "surprise"
    elif news:
        out["content_data"] = "news"
    else:
        out["content_data"] = "missing"
    return out


def enrich_content_rows(
    rows: list[dict[str, Any]],
    *,
    as_of: str | None = None,
    fetch_news: bool = False,
) -> list[dict[str, Any]]:
    return [
        enrich_content_fields(r, as_of=as_of, fetch_news=fetch_news) for r in rows
    ]


def content_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "n": len(rows),
        "with_surprise": sum(1 for r in rows if r.get("surprise")),
        "with_news": sum(1 for r in rows if r.get("news")),
        "missing": sum(1 for r in rows if r.get("content_data") == "missing"),
    }
