"""Paper trading matrix — run forward simulations across styles/strategies."""

from __future__ import annotations

from typing import Any

from signalforge.paper.runner import init_paper_portfolio, run_paper_daily

# (style, strategy) pairs simulated daily in CI and shown on the public dashboard.
# 1口座・分散フォワード（TSE 上位 TA + ルール分散）
DIVERSIFIED_PAPER_SIMULATIONS: list[tuple[str, str]] = [
    # TSE 中央値 PF 上位クラスタ
    ("swing", "bb_lower_rsi_oversold"),
    ("swing", "bnf_multi_indicator_bounce"),
    ("swing", "grid_trading_range"),
    ("swing", "bnf_ma25_kairi_reversion"),
    ("swing", "mean_reversion_short_term"),
    ("swing", "low_pbr_value_reversal"),
    # ルール系統の分散
    ("swing", "ichimoku_tk_cross"),
    ("swing", "gap_fill_reversal"),
    # ベンチマーク（TSE 中央値は弱めだが比較軸としてフォワード追跡）
    ("swing", "macd_cross"),
    ("swing", "ema_pullback"),
]

PAPER_SIMULATIONS: list[tuple[str, str]] = [
    ("swing_champion", "macd_cross"),
    ("swing", "ema_pullback"),
    ("swing", "macd_cross"),
    ("swing", "ma_golden_cross"),
    ("swing", "rsi_reversal"),
    ("swing", "bb_squeeze"),
    ("swing_high_winrate", "macd_cross"),
    ("daytrade", "vwap_ema"),
    ("daytrade", "vwap_reclaim"),
    ("daytrade", "orb"),
]

STYLE_LABELS = {
    "swing": "スイング（日足）",
    "swing_champion": "Champion（最強プリセット）",
    "swing_high_winrate": "スイング・高勝率",
    "daytrade": "デイトレ（5分足）",
}


def ensure_paper_portfolio(style: str, strategy: str, *, refresh: bool) -> None:
    from signalforge.paper.portfolio import PaperPortfolio

    if PaperPortfolio.load(style, strategy) is None:
        init_paper_portfolio(style, strategy, refresh=refresh)


def paper_portfolio_exists(strategy_id: str) -> bool:
    from signalforge.paper.portfolio import PaperPortfolio

    for style, strat in PAPER_SIMULATIONS:
        if strat == strategy_id and PaperPortfolio.load(style, strat) is not None:
            return True
    return False


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
