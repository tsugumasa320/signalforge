import pandas as pd

from signalforge.report.metrics_ja import (
    MEDIAN_PF,
    profit_check_priority_df,
    profit_check_scenario_df,
    rename_experiment_columns,
)


def test_profit_check_tables():
    p = profit_check_priority_df()
    assert len(p) >= 5
    assert "期待値（%）" in p["指標"].values
    s = profit_check_scenario_df()
    assert "TSE" in s["やりたいこと"].iloc[1] or "東証" in s["やりたいこと"].iloc[1]


def test_rename_experiment_columns():
    from signalforge.report.metrics_ja import EXPECTANCY, PROFIT_FACTOR

    df = pd.DataFrame({"profit_factor": [1.0], "expectancy_pct": [0.1], "strategy_id": ["macd_cross"]})
    out = rename_experiment_columns(df)
    assert PROFIT_FACTOR in out.columns
    assert EXPECTANCY in out.columns
    assert "戦略" in out.columns
