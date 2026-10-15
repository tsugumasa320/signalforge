"""Map strategies → alt datasets required for non-proxy backtests."""

from __future__ import annotations

from signalforge.config import load_implementation_map

TEMPLATE_DATA_DEPS: dict[str, list[str]] = {
    "sector_relative_momentum": ["sector_index"],
    "sector_spread_zscore": ["sector_index"],
    "post_earnings_drift": ["earnings"],
    "credit_margin_contrarian": ["credit_balance"],
}

# Not yet implemented — BT stays blocked or proxy until fetch exists.
PLANNED_DATASETS: dict[str, str] = {
    "minkabu_sentiment": "みんかぶ投稿数・空売り（非公開 API / スクレイプ）",
    "order_book": "板情報・VWAP  intraday",
    "sns_burst": "X/ SNS イベント系列",
}


def data_deps_for_strategy(strategy_id: str) -> list[str]:
    impl = load_implementation_map().get("strategies", {}).get(strategy_id) or {}
    deps = list(impl.get("data_deps") or [])
    template = impl.get("template") or ""
    for d in TEMPLATE_DATA_DEPS.get(template, []):
        if d not in deps:
            deps.append(d)
    return deps


def strategies_using_dataset(dataset: str) -> list[str]:
    out: list[str] = []
    for sid, spec in (load_implementation_map().get("strategies") or {}).items():
        deps = data_deps_for_strategy(sid)
        if dataset in deps:
            out.append(sid)
    return sorted(out)
