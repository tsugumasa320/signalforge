"""上昇率上位への集中。候補の切り方は成績を見る前に固定。"""

from __future__ import annotations

import pandas as pd

from signalforge.research.trend_screen.concentration import _pick, catalog
from signalforge.research.trend_screen.frequency import primary_mask


def test_catalog_has_all_and_top_cuts() -> None:
    ids = [item.id for item in catalog()]
    assert ids[0] == "all_equal"
    assert "top5_1y" in ids
    assert "top1_1y" in ids


def test_top1_picks_the_highest_one_year_return() -> None:
    index = pd.bdate_range("2018-01-01", periods=900)
    slow = pd.Series([100 * (1.0003 ** i) for i in range(900)], index=index)
    fast = pd.Series([100 * (1.0008 ** i) for i in range(900)], index=index)
    bench = pd.Series([100 * (1.0002 ** i) for i in range(900)], index=index)
    masks = {"slow": primary_mask(slow, bench), "fast": primary_mask(fast, bench)}
    day = index[-1]
    spec = next(item for item in catalog() if item.id == "top1_1y")
    assert _pick(spec, day, masks, {"slow": slow, "fast": fast}) == ["fast"]
    all_spec = next(item for item in catalog() if item.id == "all_equal")
    assert _pick(all_spec, day, masks, {"slow": slow, "fast": fast}) == ["fast", "slow"]
