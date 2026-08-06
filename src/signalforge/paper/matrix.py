"""Paper trading matrix — run forward simulations across styles/strategies."""

from __future__ import annotations

from typing import Any

from signalforge.paper.runner import init_paper_portfolio, run_paper_daily

# (style, strategy) pairs simulated daily in CI and shown on the public dashboard.
PAPER_SIMULATIONS: list[tuple[str, str]] = [
    ("swing", "ema_pullback"),
    ("swing", "macd_cross"),
    ("swing", "bb_squeeze"),
    ("swing_high_winrate", "macd_cross"),
    ("daytrade", "vwap_ema"),
    ("daytrade", "vwap_reclaim"),
    ("daytrade", "orb"),
]

STYLE_LABELS = {
    "swing": "スイング（日足）",
    "swing_high_winrate": "スイング・高勝率",
    "daytrade": "デイトレ（5分足）",
}


def ensure_paper_portfolio(style: str, strategy: str, *, refresh: bool) -> None:
    from signalforge.paper.portfolio import PaperPortfolio

    if PaperPortfolio.load(style, strategy) is None:
        init_paper_portfolio(style, strategy, refresh=refresh)


def run_all_paper_daily(
    *,
    refresh: bool = True,
    cost_model: str | None = None,
    simulations: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Advance every configured paper account; skip failures with error info."""
    pairs = simulations or PAPER_SIMULATIONS
    results: list[dict[str, Any]] = []
    for style, strategy in pairs:
        try:
            ensure_paper_portfolio(style, strategy, refresh=refresh)
            out = run_paper_daily(style, strategy, cost_model=cost_model, refresh=refresh)
            results.append({"style": style, "strategy": strategy, "ok": True, **out})
        except Exception as exc:
            results.append(
                {
                    "style": style,
                    "strategy": strategy,
                    "ok": False,
                    "error": str(exc),
                }
            )
    return results
