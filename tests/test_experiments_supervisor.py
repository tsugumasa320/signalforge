from signalforge.experiments import supervisor as sup


def test_assess_campaign_work_needs_run_when_incomplete(monkeypatch):
    monkeypatch.setattr(sup, "planned_strategy_count", lambda: 5)
    monkeypatch.setattr(sup, "_parse_strategy_ids_from_plan", lambda: ["foo"])
    monkeypatch.setattr(sup, "list_strategies_needing_metric_refresh", lambda _ids: [])

    def _scan(**kwargs):
        return {
            "complete": [],
            "in_progress": [{"strategy_id": "foo", "n_done": 3, "n_target": 10}],
            "total_planned": 5,
        }

    monkeypatch.setattr(sup, "scan_campaign_progress", _scan)

    work = sup.assess_campaign_work(mode="campaign")
    assert work.needs_run is True
    assert "checkpoint" in work.reason


def test_assess_campaign_work_idle_when_done(monkeypatch):
    monkeypatch.setattr(sup, "_parse_strategy_ids_from_plan", lambda: ["a"])
    monkeypatch.setattr(sup, "list_strategies_needing_metric_refresh", lambda _ids: [])

    def _scan(**kwargs):
        return {"complete": [{"strategy_id": "a"}], "in_progress": [], "total_planned": 1}

    monkeypatch.setattr("signalforge.experiments.supervisor.scan_campaign_progress", _scan)

    work = sup.assess_campaign_work(mode="campaign")
    assert work.needs_run is False
