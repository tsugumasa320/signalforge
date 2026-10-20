#!/usr/bin/env python3
"""Build implementation_map.yaml from web_catalog.yaml (heuristic template assignment)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "strategies" / "web_catalog.yaml"
OUT = ROOT / "config" / "strategies" / "implementation_map.yaml"

BUILTIN = {
    "macd_cross",
    "ema_pullback",
    "bb_squeeze",
    "ma_golden_cross",
    "rsi_reversal",
    "vwap_ema",
    "vwap_reclaim",
    "orb",
}


def _spec(catalog_id: str, tags: list[str], style: str) -> dict:
    t = set(tags or [])
    cid = catalog_id

    if cid in BUILTIN:
        return {"builtin": cid}

    explicit: dict[str, dict] = {
        "perfect_order_pullback": {"template": "perfect_order_pullback"},
        "ma_25_75_golden_cross": {"template": "ma_cross", "params": {"fast": "ema25", "slow": "ema75"}},
        "ma_50_200_golden_cross": {"template": "ma_cross", "params": {"fast": "ema50", "slow": "ema200"}},
        "ma_death_cross": {
            "template": "ma_cross",
            "params": {"fast": "ema50", "slow": "ema200", "direction": "dead", "long_only": False},
        },
        "ma_200_trend_filter": {"template": "ema200_filter_macd", "params": {"require_ema200": True}},
        "trend_reentry": {"template": "high_breakout_rsi", "params": {"lookback": 126, "rsi_min": 60}},
        "adx_trend_ride": {"template": "adx_trend", "params": {"adx_min": 25, "ema_col": "ema50"}},
        "supertrend_follow": {"template": "adx_trend", "params": {"adx_min": 20, "ema_col": "ema20"}},
        "heikin_ashi_trend": {"template": "heikin_ashi_trend"},
        "ichimoku_kumo_break": {"template": "ichimoku_kumo_break"},
        "ichimoku_sanyaku_koten": {"template": "ichimoku_sanyaku"},
        "ichimoku_tk_cross": {"template": "ichimoku_tk_cross"},
        "ichimoku_kijun_pullback": {"template": "ichimoku_kijun_pullback"},
        "ichimoku_macd_rsi": {"template": "combo_macd_rsi_ichimoku"},
        "rsi_dip_200ma": {"template": "rsi_oversold", "params": {"rsi_max": 35, "require_ema200": True}},
        "rsi_momentum_60": {"template": "rsi_momentum", "params": {"rsi_min": 60, "ema_col": "ema25"}},
        "bb_lower_rsi_oversold": {
            "template": "bb_rsi",
            "params": {"side": "lower", "rsi_max": 30},
        },
        "bb_upper_rsi_exit": {"template": "bb_rsi", "params": {"side": "upper", "rsi_min": 70, "signal": "short"}},
        "stoch_rsi_cross": {"template": "rsi_oversold", "params": {"rsi_max": 25, "rsi_reclaim": 25}},
        "cci_zero_cross": {"template": "cci_cross"},
        "macd_histogram_reversal": {"template": "macd_histogram_reversal"},
        "volume_breakout": {"template": "volume_breakout", "params": {"volume_ratio_min": 2.0}},
        "donchian_breakout": {"template": "donchian_breakout", "params": {"period": 20}},
        "box_range_breakout": {"template": "donchian_breakout", "params": {"period": 10}},
        "triangle_breakout": {"template": "donchian_breakout", "params": {"period": 15}},
        "keltner_squeeze": {"template": "bb_squeeze_proxy"},
        "vcp_minervini": {"template": "high_breakout_rsi", "params": {"lookback": 60, "rsi_min": 55}},
        "gap_up_continuation": {"template": "gap_up", "params": {"min_gap_pct": 0.01}},
        "gap_fill_reversal": {"template": "gap_fill_reversal"},
        "fib_pullback_382_618": {"template": "swing_pullback_ema", "params": {"ema_col": "ema50"}},
        "relative_strength_index_rs": {"template": "rsi_momentum", "params": {"rsi_min": 55}},
        "topix100_momentum": {"template": "momentum_ema", "params": {"ema_col": "ema20"}},
        "credit_balance_contrarian": {
            "template": "credit_margin_contrarian",
            "params": {"min_shrt_ratio": 0.45, "ratio_drop": 0.03, "rsi_max": 45},
            "data_deps": ["credit_balance"],
        },
        "sector_leader_laggard": {
            "template": "sector_relative_momentum",
            "params": {"lookback": 20, "min_rs_pct": 1.0, "ema_col": "ema20"},
            "data_deps": ["sector_index"],
        },
        "double_bottom_break": {"template": "donchian_breakout", "params": {"period": 40}},
        "cup_and_handle": {"template": "high_breakout_rsi", "params": {"lookback": 90, "rsi_min": 50}},
        "head_shoulders_short": {
            "template": "ma_cross",
            "params": {"fast": "ema20", "slow": "ema50", "direction": "dead", "long_only": False},
        },
        "vwap_pullback_long": {"template": "session_vwap", "params": {"mode": "pullback"}},
        "vwap_mean_reversion_short": {"template": "session_vwap", "params": {"mode": "mean_rev_short"}},
        "vwap_breakout_follow": {"template": "session_vwap", "params": {"mode": "breakout"}},
        "am_high_breakout_volume": {"template": "session_high_break", "params": {"session": "morning", "volume_ratio_min": 1.5}},
        "pm_high_breakout": {"template": "session_high_break", "params": {"session": "afternoon", "volume_ratio_min": 1.2}},
        "relative_volume_filter": {"template": "volume_breakout", "params": {"volume_ratio_min": 1.8}},
        "opening_gap_daytrade": {"template": "opening_gap_session", "params": {"min_gap_pct": 0.005}},
        "first_hour_momentum": {"template": "session_momentum", "params": {"start": "09:00", "end": "10:00", "ema_col": "ema9"}},
        "lunch_break_fade": {"template": "session_vwap_fade", "params": {"start": "11:00", "end": "11:30"}},
        "close_momentum": {"template": "session_momentum", "params": {"start": "14:30", "end": "15:00", "ema_col": "ema9"}},
        "prior_day_hl_break": {"template": "prior_day_level_break"},
        "pivot_point_bounce": {"template": "pivot_bounce"},
        "ema9_21_scalp_5m": {"template": "ma_cross", "params": {"fast": "ema9", "slow": "ema21"}},
        "parabolic_sar_intraday": {"template": "psar_flip"},
        "weekly_swing_multiframe": {"template": "ma_cross", "params": {"fast": "ema20", "slow": "ema50"}},
        "earnings_drift": {
            "template": "post_earnings_drift",
            "params": {"min_days_after": 1, "max_days_after": 5, "min_gap_pct": 0.005, "volume_ratio_min": 1.2},
            "data_deps": ["earnings"],
        },
        "low_pbr_value_reversal": {"template": "rsi_oversold", "approximation": "ファンダなし→RSI近似"},
        "momentum_monthly_rebalance": {"template": "momentum_ema", "params": {"ema_col": "ema50"}},
        "mean_reversion_short_term": {"template": "mean_reversion_rsi"},
        "pairs_trading_sector": {
            "template": "sector_spread_zscore",
            "params": {"z_col": "sector_spread_z20", "entry_z": -2.0, "exit_z": 0.0},
            "data_deps": ["sector_index"],
        },
        "index_arb_nikkei_etf": {"template": "momentum_ema", "approximation": "ETF裁定なし→トレンド近似"},
        "grid_trading_range": {"template": "bb_rsi", "params": {"side": "lower", "rsi_max": 40}},
        "dca_trend_add": {"template": "ema_pullback_proxy"},
        "trailing_atr_chandelier": {"template": "adx_trend", "params": {"adx_min": 18, "ema_col": "ema20"}},
        "multi_strategy_ensemble": {"template": "combo_macd_rsi", "approximation": "簡易複合シグナル"},
        "bnf_ma25_kairi_reversion": {
            "template": "kairi_mean_reversion",
            "params": {"ema_col": "ema25", "kairi_max_pct": -3.0},
        },
        "bnf_regime_trend_vs_fade": {"template": "adx_trend", "params": {"adx_min": 22, "ema_col": "ema25"}},
        "bnf_multi_indicator_bounce": {"template": "bb_rsi", "params": {"side": "lower", "rsi_max": 35}},
        "bnf_sector_leading_swing": {
            "template": "sector_relative_momentum",
            "params": {"lookback": 20, "min_rs_pct": 2.0, "ema_col": "ema25"},
            "data_deps": ["sector_index"],
        },
        "ch5_minority_sentiment": {"template": "volume_breakout", "approximation": "掲示板センチメントなし→出来高近似"},
        "x_keyword_material_screen": {"template": "volume_breakout", "approximation": "SNSなし→出来高近似"},
        "x_tweet_burst_filter": {"template": "volume_breakout", "params": {"volume_ratio_min": 2.5}, "approximation": "SNSなし"},
        "x_sentiment_event_factor": {"template": "gap_up", "approximation": "イベントなし→ギャップ近似"},
        "sns_sentiment_plus_ta": {"template": "combo_macd_rsi", "approximation": "SNSなし→TA複合"},
        "youtube_new_high_box_break": {"template": "donchian_breakout", "params": {"period": 20}},
        "youtube_elliott_multiframe": {"template": "ma_cross", "params": {"fast": "ema20", "slow": "ema50"}},
        "youtube_dow_theory_trend": {"template": "ma_cross", "params": {"fast": "ema50", "slow": "ema200"}},
        "vwap_orderflow_itasha": {
            "template": "session_vwap",
            "params": {"mode": "breakout"},
            "approximation": "板情報なし。セッションVWAPの抜けだけ",
        },
        "professional_daytrader_session": {
            "template": "session_momentum",
            "params": {"windows": [["09:00", "10:00"], ["14:00", "15:00"]], "ema_col": "ema9"},
            "approximation": "寄りと引けの時間帯だけ。板や習慣データはない",
        },
        "kabutan_preset_macd_buy": {"template": "builtin_macd", "params": {"ema_trend": 50}},
        "kabutan_preset_rsi_oversold": {"template": "rsi_oversold", "params": {"rsi_max": 20, "rsi_reclaim": 20}},
        "kabutan_preset_rsi_overbought": {
            "template": "rsi_momentum",
            "params": {"rsi_min": 80, "signal": "exit_short"},
        },
        "kabutan_shinchu_sanbon_inverted": {
            "template": "three_bar_reversal",
            "params": {"direction": "bearish"},
        },
        "kabutan_ma_uptrend_low_kairi25": {
            "template": "kairi_mean_reversion",
            "params": {"ema_col": "ema25", "kairi_max_pct": -1.5, "trend_ema": "ema75"},
        },
        "kabutan_contrarian_short_hold": {"template": "mean_reversion_rsi", "params": {"max_hold_hint": 5}},
        "kabutan_theme_swing_earnings": {
            "template": "post_earnings_drift",
            "params": {"min_days_after": 1, "max_days_after": 8, "min_gap_pct": 0.003, "volume_ratio_min": 1.1},
            "data_deps": ["earnings"],
        },
        "kabutan_core_satellite_credit_swing": {"template": "ma_cross", "params": {"fast": "ema20", "slow": "ema60"}},
        "kabutan_supply_ma_20_60_swing": {
            "template": "ma_cross",
            "params": {"fast": "ema20", "slow": "ema60", "trend_col": "ema5"},
        },
        "minkabu_gc_25_75_preset": {"template": "ma_cross", "params": {"fast": "ema25", "slow": "ema75"}},
        "minkabu_short_oversold_preset": {"template": "rsi_oversold", "params": {"rsi_max": 25, "rsi_reclaim": 25}},
        "minkabu_custom_technical_screen": {"template": "combo_macd_rsi"},
        "minkabu_community_sentiment_rank": {
            "template": "volume_breakout",
            "approximation": "投稿数なし→出来高近似",
        },
    }

    if cid.startswith("youtube_harvest_"):
        if style == "daytrade" or "daytrade" in t:
            return {"template": "vwap_proxy_daily", "params": {"mode": "breakout"}, "approximation": "YouTube字幕由来"}
        if "mean_reversion" in t or "逆張り" in cid:
            return {"template": "mean_reversion_rsi", "approximation": "YouTube字幕由来"}
        return {"template": "combo_macd_rsi", "approximation": "YouTube字幕由来"}

    if cid in explicit:
        spec = explicit[cid]
        return spec

    if "ichimoku" in t:
        return {"template": "ichimoku_kumo_break"}
    if "vwap" in t:
        return {"template": "vwap_proxy_daily", "approximation": "日足VWAP代理"}
    if "mean_reversion" in t or "逆張り" in cid:
        return {"template": "mean_reversion_rsi"}
    if "breakout" in t:
        return {"template": "donchian_breakout", "params": {"period": 20}}
    if "screening" in t or "kabutan" in t or "minkabu" in t:
        return {"template": "volume_breakout", "params": {"volume_ratio_min": 1.5}}
    if style == "daytrade":
        return {"template": "session_momentum", "params": {"start": "09:00", "end": "10:00", "ema_col": "ema9"}}
    if "ma" in t or "trend" in t:
        return {"template": "ma_cross", "params": {"fast": "ema20", "slow": "ema50"}}
    return {"template": "momentum_ema", "params": {"ema_col": "ema20"}, "approximation": "汎用モメンタム近似"}


def main() -> int:
    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}
    strategies: dict[str, dict] = {}
    for s in cat.get("strategies", []):
        sid = s["id"]
        spec = _spec(sid, s.get("tags") or [], s.get("style", "swing"))
        spec.setdefault("catalog_style", s.get("style", "swing"))
        strategies[sid] = spec

    doc = {
        "meta": {
            "description": "Catalog ID → backtest template (builtin or catalog_template)",
            "generated_by": "scripts/generate_implementation_map.py",
        },
        "strategies": strategies,
    }
    OUT.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Wrote {OUT} ({len(strategies)} strategies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
