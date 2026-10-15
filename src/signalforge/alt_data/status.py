from __future__ import annotations

import json
from typing import Any

from signalforge.alt_data.deps import PLANNED_DATASETS, data_deps_for_strategy
from signalforge.alt_data.credit_balance import credit_dir
from signalforge.alt_data.earnings import earnings_path
from signalforge.alt_data.paths import sector_index_meta_path, sector_indices_dir
from signalforge.alt_data.sector_index import tickers_by_sector
from signalforge.config import load_implementation_map
from signalforge.universe.tse_listing import list_tse_tickers


def alt_data_status() -> dict[str, Any]:
    sectors = tickers_by_sector()
    meta_path = sector_index_meta_path()
    built = 0
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            built = len(meta)
        except json.JSONDecodeError:
            built = len(list(sector_indices_dir().glob("*.parquet")))
    tickers = list_tse_tickers()
    earn_with = sum(1 for t in tickers if earnings_path(t).exists())
    credit_with = len(list(credit_dir().glob("*.json")))

    impl = load_implementation_map().get("strategies") or {}
    needs_alt: list[str] = []
    still_proxy: list[str] = []
    for sid, spec in impl.items():
        if spec.get("approximation"):
            still_proxy.append(sid)
        if data_deps_for_strategy(sid):
            needs_alt.append(sid)

    return {
        "sector_groups": len(sectors),
        "sector_indices_built": built,
        "earnings_files": earn_with,
        "credit_margin_files": credit_with,
        "tse_tickers": len(tickers),
        "strategies_with_data_deps": len(needs_alt),
        "strategies_still_approximation": len(still_proxy),
        "planned_datasets": PLANNED_DATASETS,
    }
