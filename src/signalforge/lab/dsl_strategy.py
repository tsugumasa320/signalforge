from __future__ import annotations

from typing import Any

import pandas as pd

from signalforge.lab.conditions import signals_from_entry_spec
from signalforge.strategies.base import BaseStrategy


class DslEntryStrategy(BaseStrategy):
    name = "dsl_entry"

    def __init__(self, cfg: dict[str, Any]) -> None:
        super().__init__(cfg)
        self.entry = cfg.get("_entry_spec", {"all": []})
        self.name = cfg.get("_catalog_id", "dsl_entry")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return signals_from_entry_spec(df, self.entry)
