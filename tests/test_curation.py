from signalforge.experiments import curation


def _row(sid: str, exp: float | None, pf: float = 1.1, wr: float = 0.4, n: int = 10) -> dict:
    return {
        "strategy_id": sid,
        "expectancy_pct": exp,
        "profit_factor": pf,
        "win_rate": wr,
        "total_trades": n,
        "metrics_trusted": exp is not None,
    }


def test_curate_merges_identical_and_hides_untrusted(monkeypatch):
    import signalforge.alt_data.trust as trust

    monkeypatch.setattr(trust, "apply_trust_to_row", lambda r: r)
    rows = [
        _row("zz_preset", 0.2),
        _row("aa_preset", 0.2),
        _row("fwd_pick", 0.2),
        _row("unique", 0.5, pf=1.3),
        _row("proxy", None),
    ]
    visible, info = curation.curate_strategy_rows(rows, preferred_ids={"fwd_pick"})
    ids = {r["strategy_id"] for r in visible}
    assert ids == {"fwd_pick", "unique"}
    head = next(r for r in visible if r["strategy_id"] == "fwd_pick")
    assert head["aliases"] == ["aa_preset", "zz_preset"]
    assert info["hidden_untrusted"] == ["proxy"]
    assert info["merged_duplicates"] == ["aa_preset", "zz_preset"]
