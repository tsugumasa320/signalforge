import pandas as pd

from signalforge.report.experiment_context import apply_ranking_filters


def test_apply_ranking_filters_pf_and_trades():
    df = pd.DataFrame(
        [
            {"strategy_id": "a", "profit_factor": 1.2, "total_trades": 50, "expectancy_pct": 0.1},
            {"strategy_id": "b", "profit_factor": 0.9, "total_trades": 100, "expectancy_pct": -0.1},
        ]
    )
    out = apply_ranking_filters(df, min_median_trades=60, profit_factor_gt_1=True)
    assert out.empty
    out = apply_ranking_filters(df, min_median_trades=40, profit_factor_gt_1=True, expectancy_positive=True)
    assert len(out) == 1 and out.iloc[0]["strategy_id"] == "a"
