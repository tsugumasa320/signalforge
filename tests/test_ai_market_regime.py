"""Market regime (地合い) from index proxies."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from signalforge.ai.market_regime import (
    analyze_series,
    build_market_regime,
    load_market_regime,
)


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    (data / "published").mkdir(parents=True)
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(data))
    return data


def _synth(start: float, n: int = 260, step: float = 1.0) -> pd.Series:
    idx = pd.date_range("2025-01-01", periods=n, freq="B", tz="UTC")
    return pd.Series([start + i * step for i in range(n)], index=idx)


def test_analyze_series_risk_on() -> None:
    s = _synth(100.0, step=0.5)
    m = analyze_series(s)
    assert m["ret_20d"] is not None and m["ret_20d"] > 0
    assert m["vs_ma200"] is not None and m["vs_ma200"] > 0
    assert m["stance"] == "risk_on"


def test_analyze_series_risk_off() -> None:
    s = _synth(200.0, step=-0.4)
    m = analyze_series(s)
    assert m["stance"] == "risk_off"


def test_build_market_regime_from_cache(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = {
        "1321.T": _synth(30000, step=20),
        "1306.T": _synth(2000, step=3),
        "^DJI": _synth(35000, step=-30),
        "^GSPC": _synth(4500, step=-2),
        "^IXIC": _synth(14000, step=-5),
    }

    def fake_load(ticker: str, *, refresh: bool = False) -> pd.Series:
        return mapping[ticker]

    monkeypatch.setattr("signalforge.ai.market_regime._load_close", fake_load)
    payload = build_market_regime(refresh=False)
    assert payload["schema"].startswith("signalforge-market-regime")
    assert payload["jp"] in {"risk_on", "mixed_on"}
    assert payload["us"] in {"risk_off", "mixed_off"}
    assert "mixed" in str(payload["overall"]) or payload["overall"] in {"risk_on", "risk_off"}

    assert len(payload["indices"]) == 5
    assert load_market_regime() is not None
    assert (data_dir / "published" / "market_regime.json").exists()
