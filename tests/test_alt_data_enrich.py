import pandas as pd

from signalforge.alt_data.enrich import enrich_dataframe


def test_enrich_sector_columns_when_index_present(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=30, freq="D")
    df = pd.DataFrame(
        {
            "close": range(100, 130),
            "volume": [1_000_000] * 30,
            "ema20": range(99, 129),
        },
        index=idx,
    )
    sec = pd.Series([100.0 + i * 0.5 for i in range(30)], index=idx)

    monkeypatch.setattr(
        "signalforge.alt_data.enrich.listing_by_ticker",
        lambda: {"7203.T": {"sector_tse": "輸送用機器"}},
    )
    monkeypatch.setattr(
        "signalforge.alt_data.enrich.load_sector_index",
        lambda _s: sec,
    )
    monkeypatch.setattr(
        "signalforge.alt_data.deps.data_deps_for_strategy",
        lambda _sid: ["sector_index"],
    )

    out = enrich_dataframe(df, "7203.T", "sector_leader_laggard")
    assert "sector_rs_20d" in out.columns
    assert out["sector_index_close"].notna().all()
