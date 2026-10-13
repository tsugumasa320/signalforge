from datetime import date

from signalforge.experiments.period import (
    period_cache_key,
    period_label,
    periods_match,
)


def test_periods_match_none_end_means_latest():
    assert periods_match(date(2020, 1, 1), None, date(2020, 1, 1), None)
    assert not periods_match(date(2020, 1, 1), None, date(2023, 1, 1), None)
    assert not periods_match(date(2020, 1, 1), date(2024, 1, 1), date(2020, 1, 1), None)


def test_period_cache_key_stable():
    a = period_cache_key(date(2023, 1, 1), None, segment="prime")
    b = period_cache_key(date(2023, 1, 1), None, segment="prime")
    c = period_cache_key(date(2023, 1, 1), None, segment="growth")
    assert a == b
    assert a != c


def test_period_label():
    assert "2023-01-01" in period_label(date(2023, 1, 1), None)
    assert "最新" in period_label(date(2023, 1, 1), None)
