"""Session rules use the clock and the previous day, not a daily-bar substitute."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from signalforge.strategies.intraday_signals import opening_gap_session, prior_day_level_break, session_momentum


def _frame(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    idx = pd.to_datetime([r[0] for r in rows]).tz_localize("Asia/Tokyo")
    return pd.DataFrame(
        {
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [1000] * len(rows),
            "ema9": [r[4] for r in rows],
        },
        index=idx,
    )


def test_opening_gap_uses_previous_session_close():
    df = _frame(
        [
            ("2026-10-16 09:00", 100, 101, 99, 100),
            ("2026-10-16 14:55", 100, 102, 99, 100),
            ("2026-10-17 09:00", 101, 103, 100, 102),
            ("2026-10-17 09:05", 102, 103, 101, 102),
        ]
    )
    signals = opening_gap_session(df, {"min_gap_pct": 0.005}, None)
    assert int(signals.iloc[2]) == 1
    assert int(signals.iloc[3]) == 0


def test_prior_day_high_break_fires_once():
    df = _frame(
        [
            ("2026-10-16 09:00", 100, 110, 99, 105),
            ("2026-10-17 09:00", 106, 108, 105, 107),
            ("2026-10-17 09:05", 108, 112, 107, 111),
            ("2026-10-17 09:10", 111, 113, 110, 112),
        ]
    )
    signals = prior_day_level_break(df, {}, None)
    assert list(signals.astype(int)) == [0, 0, 1, 0]


def test_opening_range_is_twenty_one_minute_bars():
    from signalforge.strategies.daytrade.orb import opening_range_bars

    idx = pd.date_range("2026-10-19 09:00", periods=30, freq="1min", tz="Asia/Tokyo")
    assert opening_range_bars(idx, 20) == 20
    idx5 = pd.date_range("2026-10-19 09:00", periods=10, freq="5min", tz="Asia/Tokyo")
    assert opening_range_bars(idx5, 20) == 4


def test_one_minute_history_stays_inside_yahoo_limit():
    from signalforge.data.fetcher import yfinance_history_start

    end = datetime(2026, 10, 19, 15, 30)
    start = yfinance_history_start("1m", end, datetime(2020, 1, 1))
    assert start == end - timedelta(days=6)


def test_daily_view_keeps_swing_rows():
    from signalforge.experiments.intraday_campaign import without_intraday

    rows = [
        {"strategy_id": "mean_reversion_short_term"},
        {"strategy_id": "vwap_ema"},
        {"strategy_id": "orb"},
    ]
    kept = without_intraday(rows)
    assert [r["strategy_id"] for r in kept] == ["mean_reversion_short_term"]


def test_intraday_rows_keep_missing_strategies(tmp_path, monkeypatch):
    from signalforge.experiments import intraday_campaign as camp

    monkeypatch.setattr(camp, "campaign_dir", lambda folder: tmp_path / folder)
    rows = camp.intraday_result_rows()
    assert len(rows) == len(camp.PRICE_INTRADAY_STRATEGIES) * 2
    assert {r["timeframe"] for r in rows} == {"5m", "1m"}
    assert all(r["status"] == "未着手" for r in rows)


def test_first_hour_momentum_ignores_the_afternoon():
    df = _frame(
        [
            ("2026-10-17 09:00", 100, 101, 99, 100),
            ("2026-10-17 09:30", 100, 103, 100, 102),
            ("2026-10-17 14:30", 102, 106, 102, 105),
        ]
    )
    df["ema9"] = [100, 100, 100]
    signals = session_momentum(df, {"start": "09:00", "end": "10:00", "ema_col": "ema9"}, None)
    assert int(signals.iloc[1]) == 1
    assert int(signals.iloc[2]) == 0
