#!/usr/bin/env python3
"""Fill missing `name` / yfinance sector hints in japan_equity_meta.yaml (segment stays manual)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "config" / "universe" / "japan_equity_meta.yaml"


def main() -> int:
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance required", file=sys.stderr)
        return 1

    doc = yaml.safe_load(META.read_text(encoding="utf-8")) or {}
    tickers = doc.get("tickers", {})
    for sym, meta in tickers.items():
        if sym.endswith(".T") is False:
            continue
        info = yf.Ticker(sym).info
        if not meta.get("name") and info.get("shortName"):
            meta["name"] = info["shortName"]
        if not meta.get("sector_yf") and info.get("sector"):
            meta["sector_yf"] = info["sector"]
    META.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Updated {META} ({len(tickers)} tickers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
