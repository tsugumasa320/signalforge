from __future__ import annotations

import hashlib
import re
from pathlib import Path

from signalforge.config import data_dir


def alt_data_root() -> Path:
    p = data_dir() / "alt"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sector_indices_dir() -> Path:
    p = alt_data_root() / "sector_indices"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sector_index_meta_path() -> Path:
    return sector_indices_dir() / "_meta.json"


def sector_index_path(sector_tse: str) -> Path:
    safe = hashlib.sha256(sector_tse.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^\w\u3000-\u9fff-]+", "_", sector_tse.strip())[:48]
    return sector_indices_dir() / f"{safe}_{slug}.parquet"


def earnings_dir() -> Path:
    p = alt_data_root() / "earnings"
    p.mkdir(parents=True, exist_ok=True)
    return p


def earnings_path(ticker: str) -> Path:
    safe = ticker.replace("/", "_")
    return earnings_dir() / f"{safe}.json"
