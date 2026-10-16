from signalforge.paper.diversified_specs import DIVERSIFIED_PAPER_SIMULATIONS
from signalforge.report.static_site import hub_guide_strategy_ids


def test_hub_guide_ids_include_diversified_and_top_tse():
    tse_rows = [
        {"strategy": "aaa", "expectancy_pct": 1.0},
        {"strategy": "bbb", "expectancy_pct": 0.5},
    ]
    ids = hub_guide_strategy_ids(tse_rows, top_n=1)
    assert "aaa" in ids
    assert "bbb" not in ids
    assert all(spec.strategy in ids for spec in DIVERSIFIED_PAPER_SIMULATIONS)
