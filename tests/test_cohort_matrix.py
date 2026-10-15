from signalforge.experiments.cohort_matrix import breakdown_rows_for_strategy, build_cohort_matrix


def test_breakdown_rows_segment_and_sector() -> None:
    doc = {
        "complete": True,
        "style": "swing",
        "universe": {"n_tickers": 100, "median_profit_factor": 1.1, "n_ok": 100},
        "by_segment": {
            "prime": {"n_tickers": 50, "median_profit_factor": 1.2, "n_ok": 50},
        },
        "by_sector": {
            "電気機器": {"n_tickers": 10, "median_profit_factor": 1.05, "n_ok": 10},
        },
    }
    rows = breakdown_rows_for_strategy("test_strat", doc)
    kinds = {r["cohort_kind"] for r in rows}
    assert kinds == {"universe", "segment", "sector"}
    assert any(r["cohort_label"] == "プライム" for r in rows)


def test_build_masks_untrusted(monkeypatch) -> None:
    doc = {
        "complete": True,
        "style": "swing",
        "universe": {"n_tickers": 10, "median_profit_factor": 2.0, "n_ok": 10},
        "by_segment": {},
        "by_sector": {},
    }

    def _load(sid: str):
        return doc if sid == "x" else None

    monkeypatch.setattr("signalforge.experiments.cohort_matrix.load_strategy_header", _load)
    rows = build_cohort_matrix(
        [
            {
                "strategy_id": "x",
                "metrics_trusted": False,
                "metrics_note": "approx",
            }
        ]
    )
    assert len(rows) >= 1
    assert rows[0]["profit_factor"] is None
    assert rows[0]["metrics_note"] == "approx"
