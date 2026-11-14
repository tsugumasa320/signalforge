"""流動性上位の母集団。既存の日足キャッシュから作る。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from signalforge.config import data_dir
from signalforge.research.trend_screen.cases import case_tickers
from signalforge.research.trend_screen.universe import is_common_code


def liquid_universe(limit: int = 300, *, min_bars: int = 800) -> list[str]:
    from signalforge.universe.tse_listing import listing_by_ticker

    listing = listing_by_ticker()
    root = data_dir()
    scored: list[tuple[float, str]] = []
    for path in root.glob("*_1d.pkl"):
        ticker = path.name.replace("_1d.pkl", "")
        if not is_common_code(ticker):
            continue
        row = listing.get(ticker)
        if not row or row.get("segment") not in {"prime", "standard", "growth"}:
            continue
        try:
            frame = pd.read_pickle(path)
        except Exception:
            continue
        if len(frame) < min_bars or "close" not in frame.columns or "volume" not in frame.columns:
            continue
        close = pd.to_numeric(frame["close"], errors="coerce")
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        traded = (close * volume).dropna().tail(20)
        if len(traded) < 20:
            continue
        scored.append((float(traded.mean()), ticker))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen = [ticker for _, ticker in scored[:limit]]
    for ticker in case_tickers():
        if ticker not in chosen:
            chosen.append(ticker)
    return chosen


def write_liquid_list(limit: int = 300) -> Path:
    path = data_dir() / "trend_screen" / f"liquid{limit}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    names = liquid_universe(limit)
    path.write_text("\n".join(names) + "\n", encoding="utf-8")
    return path


def read_liquid_list(limit: int = 300) -> list[str]:
    path = data_dir() / "trend_screen" / f"liquid{limit}.txt"
    if not path.exists():
        write_liquid_list(limit)
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
