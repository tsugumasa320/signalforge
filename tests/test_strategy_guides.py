"""Strategy guide resolution for full web catalog."""

from signalforge.config import load_implementation_map, load_web_catalog
from signalforge.report.strategy_guide_builder import resolve_strategy_guide


def _implemented_ids() -> list[str]:
    return [
        str(s["id"])
        for s in load_web_catalog().get("strategies", [])
        if s.get("implemented") and s.get("id")
    ]


def test_all_implemented_strategies_have_guides():
    impl = load_implementation_map().get("strategies") or {}
    for sid in _implemented_ids():
        g = resolve_strategy_guide(sid)
        assert g.get("title"), sid
        assert g.get("concept") and g["concept"] != "—", sid
        assert g.get("entry_long"), sid
        assert g.get("exit"), sid
        assert sid in impl or sid in {
            "macd_cross",
            "ema_pullback",
            "bb_squeeze",
            "ma_golden_cross",
            "rsi_reversal",
            "vwap_ema",
            "vwap_reclaim",
            "orb",
        }


def test_template_guides_use_known_templates():
    impl = load_implementation_map().get("strategies") or {}
    unknown = []
    for sid in _implemented_ids():
        spec = impl.get(sid) or {}
        if spec.get("builtin"):
            continue
        tpl = spec.get("template")
        if tpl in (None, "builtin_macd"):
            continue
        g = resolve_strategy_guide(sid)
        if "要確認" in g.get("concept", ""):
            unknown.append(sid)
    assert unknown == []
