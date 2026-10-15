import pandas as pd

from signalforge.lab.portfolio_sim import equity_daily_from_accepted, simulate_diversified_portfolio, unpack_equity_daily
from signalforge.report.benchmark import align_benchmark_to_equity


def test_equity_daily_steps_at_exit() -> None:
    accepted = [
        {"exit_ts": pd.Timestamp("2024-01-10", tz="UTC"), "pnl_jpy": 50_000},
        {"exit_ts": pd.Timestamp("2024-01-20", tz="UTC"), "pnl_jpy": -20_000},
    ]
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-01-25", tz="UTC")
    eq = equity_daily_from_accepted(1_000_000, accepted, start=start, end=end)
    assert float(eq.iloc[0]) == 1_000_000
    assert float(eq.loc[pd.Timestamp("2024-01-10", tz="UTC")]) == 1_050_000
    assert float(eq.loc[pd.Timestamp("2024-01-20", tz="UTC")]) == 1_030_000


def test_sim_includes_equity_daily_pack() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-02"]),
            "exit_time": pd.to_datetime(["2024-01-08"]),
            "pnl_pct": [5.0],
        }
    )
    out = simulate_diversified_portfolio(
        trades,
        initial_capital=1_000_000,
        max_positions=1,
        position_pct=0.5,
        chart_start=pd.Timestamp("2024-01-01"),
        chart_end=pd.Timestamp("2024-01-10"),
    )
    packed = out.get("equity_daily") or {}
    eq = unpack_equity_daily(packed)
    assert len(eq) >= 5
    assert float(eq.iloc[-1]) > 1_000_000


def test_align_benchmark_index100() -> None:
    idx = pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC")
    equity = pd.Series([1_000_000, 1_010_000, 1_020_000, 1_015_000, 1_030_000], index=idx)
    bench = pd.Series([1000, 1010, 1005, 1020, 1015], index=idx)
    eq_i, bm_i = align_benchmark_to_equity(equity, bench)
    assert abs(float(eq_i.iloc[0]) - 100.0) < 1e-6
    assert abs(float(bm_i.iloc[0]) - 100.0) < 1e-6
