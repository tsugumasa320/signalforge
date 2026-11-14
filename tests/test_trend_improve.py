"""改善案カタログと選定ロジック。"""

from __future__ import annotations

import pandas as pd

from signalforge.research.trend_screen.frequency import primary_mask
from signalforge.research.trend_screen.improve import catalog, select_names
from signalforge.research.trend_screen.ruleset import load_adopted, rules_markdown


def test_improve_catalog_is_ten_and_starts_from_base() -> None:
    ids = [item.id for item in catalog()]
    assert len(ids) == 10
    assert ids[0] == "base_top5_equal"


def test_sector_cap_skips_third_name_in_same_sector() -> None:
    index = pd.bdate_range("2018-01-01", periods=900)
    def series(growth: float) -> pd.Series:
        return pd.Series([100 * ((1 + growth) ** i) for i in range(900)], index=index)

    a = series(0.0009)
    b = series(0.0008)
    c = series(0.0007)
    d = series(0.0006)
    bench = series(0.0002)
    closes = {"A.T": a, "B.T": b, "C.T": c, "D.T": d}
    volumes = {code: pd.Series(1_000_000.0, index=index) for code in closes}
    masks = {code: primary_mask(px, bench) for code, px in closes.items()}
    sectors = {"A.T": "情報・通信業", "B.T": "情報・通信業", "C.T": "情報・通信業", "D.T": "小売業"}
    spec = next(item for item in catalog() if item.id == "top5_sector2")
    chosen = select_names(spec, index[-1], masks, closes, volumes, sectors)
    assert "A.T" in chosen and "B.T" in chosen
    assert "C.T" not in chosen
    assert "D.T" in chosen


def test_rules_markdown_mentions_rank() -> None:
    text = rules_markdown(load_adopted())
    assert "上位" in text
