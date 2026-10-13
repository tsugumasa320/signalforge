from signalforge.experiments.scan import (
    apply_cohort_to_complete,
    planned_strategy_count,
    scan_campaign_progress,
)


def test_planned_strategy_count_matches_catalog():
    n = planned_strategy_count()
    assert n >= 100


def test_scan_campaign_progress_shape():
    scan = scan_campaign_progress()
    assert "complete" in scan and "in_progress" in scan
    assert scan["total_planned"] == planned_strategy_count()
    ov = scan.get("overall") or {}
    assert "strategy_overall_pct" in ov
    assert "ticker_overall_pct" in ov


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


def test_apply_cohort_filters_by_segment(tmp_path):
    strat = tmp_path / "strategies"
    strat.mkdir()
    sidecar = [
        {
            "ticker": "1111.T",
            "segment": "prime",
            "profit_factor": 2.0,
            "win_rate": 0.6,
            "total_trades": 10,
            "avg_pnl_pct": 1.0,
            "max_drawdown_pct": 5.0,
        },
        {
            "ticker": "2222.T",
            "segment": "growth",
            "profit_factor": 0.5,
            "win_rate": 0.4,
            "total_trades": 8,
            "avg_pnl_pct": -0.5,
            "max_drawdown_pct": 12.0,
        },
    ]
    (strat / "bar.tickers.json").write_text(
        __import__("json").dumps(sidecar, ensure_ascii=False),
        encoding="utf-8",
    )
    (strat / "bar.json").write_text(
        __import__("json").dumps(
            {
                "strategy_id": "bar",
                "complete": True,
                "n_tickers_target": 2,
                "n_tickers_done": 2,
                "tickers_file": "bar.tickers.json",
                "universe": {"median_profit_factor": 1.25, "n_tickers": 2},
                "by_segment": {
                    "prime": {"median_profit_factor": 2.0, "n_tickers": 1},
                    "growth": {"median_profit_factor": 0.5, "n_tickers": 1},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    base = [
        {
            "strategy_id": "bar",
            "style": "swing",
            "profit_factor": 1.25,
            "expectancy_pct": 0.25,
            "capital_ok": True,
            "paper_active": False,
            "mtime": 0.0,
        }
    ]
    prime = apply_cohort_to_complete(base, segment="prime", strategies_dir=strat)
    assert len(prime) == 1
    assert prime[0]["profit_factor"] == 2.0
    assert prime[0]["n_tickers"] == 1
    growth = apply_cohort_to_complete(base, segment="growth", strategies_dir=strat)
    assert growth[0]["profit_factor"] == 0.5
