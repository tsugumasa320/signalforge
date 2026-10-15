from signalforge.alt_data.trust import apply_trust_to_row, strategy_trust


def test_approximation_strategy_blanks_metrics(monkeypatch):
    monkeypatch.setattr(
        "signalforge.alt_data.trust.load_implementation_map",
        lambda: {
            "strategies": {
                "foo": {"approximation": "テスト代理", "template": "momentum_ema"},
            }
        },
    )
    t = strategy_trust("foo")
    assert t["display_metrics"] is False
    row = apply_trust_to_row(
        {"strategy_id": "foo", "expectancy_pct": 1.0, "profit_factor": 1.2}
    )
    assert row["expectancy_pct"] is None
    assert row["metrics_note"] == "代理BT（データ不足）"
