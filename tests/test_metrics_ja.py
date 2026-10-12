import pandas as pd

from signalforge.report.metrics_ja import MEDIAN_PF, rename_experiment_columns


def test_rename_experiment_columns():
    df = pd.DataFrame({"median_pf": [1.0], "strategy_id": ["macd_cross"]})
    out = rename_experiment_columns(df)
    assert MEDIAN_PF in out.columns
    assert "戦略" in out.columns
