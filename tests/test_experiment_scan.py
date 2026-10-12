from signalforge.experiments.scan import planned_strategy_count, scan_campaign_progress


def test_planned_strategy_count_matches_catalog():
    n = planned_strategy_count()
    assert n >= 100


def test_scan_campaign_progress_shape():
    scan = scan_campaign_progress()
    assert "complete" in scan and "in_progress" in scan
    assert scan["total_planned"] == planned_strategy_count()


def test_scan_ignores_tickers_sidecar_files(tmp_path):
    strat = tmp_path / "strategies"
    strat.mkdir()
    (strat / "foo.tickers.json").write_text("[{\"ticker\": \"7203.T\"}]", encoding="utf-8")
    (strat / "foo.json").write_text(
        '{"strategy_id":"foo","complete":true,"n_tickers_target":1,"n_tickers_done":1,"universe":{"median_profit_factor":1.1,"n_tickers":1}}',
        encoding="utf-8",
    )
    scan = scan_campaign_progress(strategies_dir=strat)
    assert len(scan["complete"]) == 1
    assert scan["complete"][0]["strategy_id"] == "foo"
