from signalforge.experiments.live_progress import (
    format_eta,
    format_tqdm_bar,
    format_tqdm_line,
)


def test_format_tqdm_bar():
    s = format_tqdm_bar(50.0, width=10)
    assert "50.0%" in s
    assert "|" in s
    assert "█" in s
    assert "░" in s


def test_format_tqdm_line_includes_counters():
    line = format_tqdm_line("銘柄BT", 100, 1000, pct=10.0, elapsed=60.0, eta=540.0, rate=1.5)
    assert "100/1,000" in line
    assert "it/s" in line


def test_format_eta():
    assert format_eta(45) == "45s"
    assert ":" in format_eta(3661)
