#!/usr/bin/env python3
"""Expand web_catalog from kabutan technical presets + harvest keywords."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "strategies" / "web_catalog.yaml"
HARVEST = ROOT / "data" / "strategy_harvest" / "mentions.json"
KABUTAN_TECH = "https://s.kabutan.jp/tansaku/technical/"

# 株探銘柄探検でよく使われる mode（HTML に mode= が無い場合のフォールバック）
KABUTAN_PRESET_URLS: list[tuple[str, str]] = [
    ("MACD/買いシグナル", "https://kabutan.jp/tansaku/?market=1&mode=2_0440"),
    ("新値3本足陰転", "https://kabutan.jp/tansaku/?market=&mode=2_0493"),
    ("RSI14 20%以下", "https://kabutan.jp/tansaku/?market=1&mode=2_0410"),
    ("RSI14 80%以上", "https://kabutan.jp/tansaku/?market=1&mode=2_0411"),
    ("25日線カイリ率-5%以下", "https://kabutan.jp/tansaku/?market=1&mode=2_0455"),
    ("5日線上抜け", "https://kabutan.jp/tansaku/?market=1&mode=2_0401"),
    ("ゴールデンクロス5-25", "https://kabutan.jp/tansaku/?market=1&mode=2_0420"),
    ("デッドクロス5-25", "https://kabutan.jp/tansaku/?market=1&mode=2_0421"),
    ("出来高急増", "https://kabutan.jp/tansaku/?market=1&mode=2_0460"),
    ("ボリンジャー-2σ付近", "https://kabutan.jp/tansaku/?market=1&mode=2_0430"),
]


def _fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "SignalForgeStrategyHarvest/1.0"})
    with urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _kabutan_modes(html: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for m in re.finditer(r'href="(/tansaku/\?[^"]*mode=[^"]+)"[^>]*>([^<]+)', html):
        path, label = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        url = urljoin("https://kabutan.jp", path.replace("&amp;", "&"))
        if len(label) < 2:
            continue
        found.append((label, url))
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for label, url in found:
        if url in seen:
            continue
        seen.add(url)
        out.append((label, url))
    return out


def main() -> int:
    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}
    strategies = list(cat.get("strategies", []))
    existing_ids = {s["id"] for s in strategies}
    existing_urls = {src.get("url") for s in strategies for src in s.get("sources", []) if src.get("url")}

    added = 0
    try:
        html = _fetch(KABUTAN_TECH)
        for label, url in _kabutan_modes(html):
            if url in existing_urls:
                continue
            sid = "kabutan_auto_" + re.sub(r"[^a-z0-9]+", "_", label.lower())[:48].strip("_")
            if sid in existing_ids:
                sid = f"{sid}_{added}"
            strategies.append(
                {
                    "id": sid,
                    "name": f"株探プリセット — {label}",
                    "implemented": False,
                    "style": "swing",
                    "tags": ["screening", "kabutan", "auto_harvest"],
                    "sources": [{"type": "kabutan", "title": label, "url": url}],
                }
            )
            existing_ids.add(sid)
            existing_urls.add(url)
            added += 1
    except Exception as exc:
        print(f"kabutan expand skipped: {exc}", file=sys.stderr)

    for label, url in KABUTAN_PRESET_URLS:
        if url in existing_urls:
            continue
        sid = "kabutan_preset_" + re.sub(r"[^a-z0-9]+", "_", label.lower())[:40].strip("_")
        if sid in existing_ids:
            continue
        strategies.append(
            {
                "id": sid,
                "name": f"株探プリセット — {label}",
                "implemented": False,
                "style": "swing",
                "tags": ["screening", "kabutan", "auto_harvest"],
                "sources": [{"type": "kabutan", "title": label, "url": url}],
            }
        )
        existing_ids.add(sid)
        existing_urls.add(url)
        added += 1

    if HARVEST.exists():
        harvest = json.loads(HARVEST.read_text(encoding="utf-8"))
        for src in harvest.get("sources", []):
            if src.get("kind") != "youtube":
                continue
            vid = src.get("video_id")
            if not vid or src.get("error"):
                continue
            url = f"https://www.youtube.com/watch?v={vid}"
            if url in existing_urls:
                continue
            sid = f"youtube_harvest_{vid}"
            if sid in existing_ids:
                continue
            hits = src.get("hits") or {}
            top_kw = ", ".join(k for k, _ in sorted(hits.items(), key=lambda x: -x[1])[:4])
            label = src.get("label") or vid
            style = "daytrade" if any(k in hits for k in ("デイトレ", "VWAP", "ORB", "スキャル")) else "swing"
            strategies.append(
                {
                    "id": sid,
                    "name": f"YouTube字幕 — {label}",
                    "implemented": False,
                    "style": style,
                    "tags": ["youtube_transcript", "auto_harvest"],
                    "sources": [
                        {
                            "type": "youtube_transcript",
                            "title": f"{label}（字幕キーワード: {top_kw or '—'}）",
                            "url": url,
                        }
                    ],
                }
            )
            existing_ids.add(sid)
            existing_urls.add(url)
            added += 1

        totals = harvest.get("keyword_totals", {})
        for kw, count in sorted(totals.items(), key=lambda x: -x[1]):
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", kw).strip("_") or hashlib.md5(kw.encode()).hexdigest()[:10]
            sid = f"harvest_kw_{slug}"
            if sid in existing_ids or count < 15:
                continue
            strategies.append(
                {
                    "id": sid,
                    "name": f"収集キーワード由来 — {kw}（{count}ヒット）",
                    "implemented": False,
                    "style": "swing",
                    "tags": ["auto_harvest", "keyword"],
                    "sources": [{"type": "blog", "title": "strategy_harvest mentions.json", "url": ""}],
                }
            )
            existing_ids.add(sid)
            added += 1

    cat["strategies"] = strategies
    meta = cat.setdefault("meta", {})
    meta["last_collection"] = "2026-03-23"
    CATALOG.write_text(yaml.safe_dump(cat, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Catalog updated: +{added} entries, total {len(strategies)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
