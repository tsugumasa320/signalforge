#!/usr/bin/env python3
"""Fetch media seed URLs and extract trading-strategy keyword hits.

Sources: config/strategies/media_sources.yaml (+ collection_seeds.yaml for YouTube IDs).
This does NOT replace human curation. It helps discover phrases to add to web_catalog.yaml.

  uv run python scripts/collect_strategy_mentions.py
  uv run python scripts/collect_strategy_mentions.py --youtube --max-urls 50
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "config" / "strategies" / "media_sources.yaml"
SEEDS = ROOT / "config" / "strategies" / "collection_seeds.yaml"
OUT = ROOT / "data" / "strategy_harvest" / "mentions.json"

KEYWORDS = [
    "乖離率",
    "ゴールデンクロス",
    "デッドクロス",
    "パーフェクトオーダー",
    "三役好転",
    "一目均衡",
    "VWAP",
    "ORB",
    "寄付",
    "前場高値",
    "出来高",
    "RSI",
    "MACD",
    "ボリンジャー",
    "逆張り",
    "順張り",
    "スイング",
    "デイトレ",
    "スキャル",
    "板読",
    "歩み値",
    "ストップ高",
    "新高値",
    "押し目",
    "損切",
    "少数派",
    "信用残",
    "エリオット",
    "ダウ理論",
    "新値3本足",
    "カイリ",
    "銘柄探検",
    "スクリーニング",
    "売られすぎ",
    "買われすぎ",
]

SKIP_FETCH_POLICIES = frozenset({"skip"})


def _iri_to_uri(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.hostname.encode("idna").decode("ascii") if parts.hostname else parts.netloc
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(
        (
            parts.scheme,
            netloc,
            quote(parts.path, safe="/%:@"),
            quote(parts.query, safe="=&%?"),
            parts.fragment,
        )
    )


def _fetch(url: str, timeout: int = 25) -> str:
    url = _iri_to_uri(url)
    req = Request(url, headers={"User-Agent": "SignalForgeStrategyHarvest/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _count_keywords(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for kw in KEYWORDS:
        n = len(re.findall(re.escape(kw), text))
        if n:
            counts[kw] = n
    return counts


def _youtube_transcript(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=["ja", "en"])
        return " ".join(snippet.text for snippet in fetched)
    except Exception:
        return None


def _iter_url_jobs() -> list[dict]:
    import yaml

    seen: set[str] = set()
    jobs: list[dict] = []

    media = yaml.safe_load(MEDIA.read_text(encoding="utf-8")) or {}
    for outlet in media.get("outlets", []):
        policy = (outlet.get("fetch_policy") or "fetch").strip()
        oid = outlet.get("id", "?")
        category = outlet.get("category", "?")
        name = outlet.get("name", oid)
        urls = outlet.get("urls") or []

        if policy in SKIP_FETCH_POLICIES and not urls:
            jobs.append(
                {
                    "action": "skip_outlet",
                    "outlet_id": oid,
                    "category": category,
                    "name": name,
                    "reason": policy,
                }
            )
            continue

        if policy in SKIP_FETCH_POLICIES:
            for item in urls:
                u = item.get("url", "")
                if u and u not in seen:
                    seen.add(u)
                    jobs.append(
                        {
                            "action": "skip_url",
                            "outlet_id": oid,
                            "category": category,
                            "url": u,
                            "label": item.get("label"),
                            "reason": policy,
                        }
                    )
            continue

        for item in urls:
            url = item.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            if "x.com/search" in url or "twitter.com/search" in url:
                jobs.append(
                    {
                        "action": "skip_url",
                        "outlet_id": oid,
                        "category": category,
                        "url": url,
                        "label": item.get("label"),
                        "reason": "x_search_login_wall",
                    }
                )
                continue
            jobs.append(
                {
                    "action": "fetch",
                    "outlet_id": oid,
                    "category": category,
                    "name": name,
                    "url": url,
                    "label": item.get("label"),
                    "fetch_policy": policy,
                }
            )

    seeds = yaml.safe_load(SEEDS.read_text(encoding="utf-8")) or {}
    for group, items in (seeds.get("seeds") or {}).items():
        if group == "youtube":
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            if "x.com/search" in url:
                jobs.append(
                    {
                        "action": "skip_url",
                        "outlet_id": group,
                        "category": "legacy_seed",
                        "url": url,
                        "label": item.get("label"),
                        "reason": "x_search_login_wall",
                    }
                )
                continue
            jobs.append(
                {
                    "action": "fetch",
                    "outlet_id": group,
                    "category": "legacy_seed",
                    "url": url,
                    "label": item.get("label"),
                    "fetch_policy": "legacy",
                }
            )

    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest strategy keyword mentions from media URLs")
    parser.add_argument("--youtube", action="store_true", help="Fetch YouTube subtitles (needs youtube-transcript-api)")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--max-urls", type=int, default=0, help="Limit fetch count (0 = all)")
    parser.add_argument("--delay", type=float, default=0.35, help="Seconds between HTTP requests")
    args = parser.parse_args()

    import yaml

    jobs = _iter_url_jobs()
    report: dict = {
        "meta": {"media_registry": str(MEDIA.relative_to(ROOT)), "seeds": str(SEEDS.relative_to(ROOT))},
        "stats": {"fetch_ok": 0, "fetch_error": 0, "skipped": 0, "youtube_ok": 0, "youtube_error": 0},
        "sources": [],
        "keyword_totals": {},
        "note": [],
    }

    fetch_budget = args.max_urls if args.max_urls > 0 else None
    fetched = 0

    for job in jobs:
        action = job["action"]
        if action == "skip_outlet":
            report["stats"]["skipped"] += 1
            report["sources"].append(
                {
                    "kind": job["outlet_id"],
                    "category": job["category"],
                    "skipped": job["reason"],
                    "name": job.get("name"),
                }
            )
            continue
        if action == "skip_url":
            report["stats"]["skipped"] += 1
            report["sources"].append(
                {
                    "kind": job["outlet_id"],
                    "category": job["category"],
                    "url": job["url"],
                    "label": job.get("label"),
                    "skipped": job["reason"],
                }
            )
            continue

        if fetch_budget is not None and fetched >= fetch_budget:
            report["note"].append(f"Stopped at --max-urls={fetch_budget}")
            break

        url = job["url"]
        timeout = 18 if job.get("fetch_policy") == "limited" else 25
        try:
            text = _fetch(url, timeout=timeout)
            hits = _count_keywords(text)
            report["sources"].append(
                {
                    "kind": job["outlet_id"],
                    "category": job["category"],
                    "url": url,
                    "label": job.get("label"),
                    "hits": hits,
                }
            )
            report["stats"]["fetch_ok"] += 1
            fetched += 1
            for k, v in hits.items():
                report["keyword_totals"][k] = report["keyword_totals"].get(k, 0) + v
        except Exception as exc:
            report["sources"].append(
                {
                    "kind": job["outlet_id"],
                    "category": job["category"],
                    "url": url,
                    "label": job.get("label"),
                    "error": str(exc),
                }
            )
            report["stats"]["fetch_error"] += 1
            fetched += 1

        if args.delay > 0:
            time.sleep(args.delay)

    seeds = yaml.safe_load(SEEDS.read_text(encoding="utf-8")) or {}
    if args.youtube:
        for item in seeds.get("seeds", {}).get("youtube", []):
            vid = item.get("video_id")
            if not vid:
                continue
            text = _youtube_transcript(vid)
            if text is None:
                report["sources"].append(
                    {
                        "kind": "youtube",
                        "video_id": vid,
                        "error": "字幕取得失敗 or youtube-transcript-api 未インストール",
                    }
                )
                report["stats"]["youtube_error"] += 1
                continue
            hits = _count_keywords(text)
            report["sources"].append({"kind": "youtube", "video_id": vid, "label": item.get("label"), "hits": hits})
            report["stats"]["youtube_ok"] += 1
            for k, v in hits.items():
                report["keyword_totals"][k] = report["keyword_totals"].get(k, 0) + v
    else:
        report["note"].append("YouTube 字幕は未実行（--youtube と youtube-transcript-api）")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    st = report["stats"]
    print(
        f"HTTP ok={st['fetch_ok']} err={st['fetch_error']} skipped={st['skipped']} "
        f"| YouTube ok={st['youtube_ok']} err={st['youtube_error']}"
    )
    top = sorted(report["keyword_totals"].items(), key=lambda x: -x[1])[:12]
    if top:
        print("Top keywords:", ", ".join(f"{k}({v})" for k, v in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
