"""採用シストレ規則の固定。"""

from __future__ import annotations

from signalforge.research.trend_screen.ruleset import DEFAULT_SYSTEM_ID, load_adopted, rules_markdown
from signalforge.research.trend_screen.system import adopted_spec


def test_default_adopted_is_top5_equal() -> None:
    rules = load_adopted()
    # adopted.json が無い環境ではデフォルト
    if not rules.id.startswith("trend_top") and rules.version == "1.0":
        assert rules.id == DEFAULT_SYSTEM_ID
        assert rules.top_n == 5
        assert rules.rank_by == "ret_1y"
        assert rules.weight == "equal"
    spec = adopted_spec()
    assert spec.top_n == rules.top_n
    assert spec.rank_by == rules.rank_by


def test_rules_markdown_states_what_was_rejected() -> None:
    text = rules_markdown()
    assert "毎日判定" in text
    assert "地合い" in text
