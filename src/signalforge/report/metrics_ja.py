"""Japanese labels and short explanations for backtest / experiment metrics."""

from __future__ import annotations

# --- Display names (UI・CLI) ---

PROFIT_FACTOR = "損益比"
PROFIT_FACTOR_LONG = "損益比（PF）"
EXPECTANCY = "期待値（%）"
WIN_RATE = "勝率"
MAX_DRAWDOWN = "最大DD（%）"
PORTFOLIO_RETURN = "1口座リターン（%）"
TRADES = "取引数"
STRATEGY_SUMMARY = "解説"
STRATEGY_CATEGORY = "分類"
STRATEGY_RANK = "#"
METRICS_NOTE = "データ"
TSE_TABLE_NOTE = "各列は全銘柄バックテスト結果の典型値（順位の真ん中の銘柄）"

STRATEGY_TAG_LABELS: dict[str, str] = {
    "trend": "トレンド",
    "momentum": "モメンタム",
    "ma": "移動平均",
    "mean_reversion": "逆張り",
    "breakout": "ブレイクアウト",
    "volatility": "ボラティリティ",
    "vwap": "VWAP",
    "daytrade": "デイトレ",
    "opening": "寄り付き",
    "ichimoku": "一目",
    "oscillator": "オシレーター",
    "rsi": "RSI",
    "bb": "ボリンジャー",
    "pattern": "パターン",
    "pullback": "押し目",
    "japan": "日本株定番",
    "screening": "スクリーニング",
    "kabutan": "株探系",
    "minkabu": "みんかぶ系",
    "dsl": "DSL",
    "combo": "複合",
    "gap": "ギャップ",
    "volume": "出来高",
    "adx": "ADX",
    "atr": "ATR",
    "candle": "ローソク",
    "fibonacci": "フィボナッチ",
    "sector": "セクター",
    "relative_strength": "相対強度",
    "multi_timeframe": "マルチTF",
    "regime": "レジーム",
    "quant": "クオンツ",
    "factor": "ファクター",
    "value": "バリュー",
    "growth": "グロース",
    "event": "イベント",
    "sentiment": "センチメント",
    "orderflow": "フロー",
    "scalp": "スキャル",
    "scalping": "スキャル",
    "range": "レンジ",
    "grid": "グリッド",
    "portfolio": "ポートフォリオ",
    "position_sizing": "ポジションサイズ",
    "market_neutral": "マーケットニュートラル",
    "arb": "アービトラージ",
    "fundamental": "ファンダ",
    "supply_demand": "需給",
    "session": "セッション",
    "levels": "水平線",
    "exit": "出口",
    "meta": "メタ",
    "auto_harvest": "収集候補",
    "keyword": "キーワード",
    "crypto_style": "暗号資産型",
    "2ch": "2ch",
    "x": "X",
    "youtube": "YouTube",
    "youtube_transcript": "YouTube字幕",
}


def format_strategy_tags(tags: list[str] | None) -> str:
    if not tags:
        return "—"
    labels = [STRATEGY_TAG_LABELS.get(str(t).strip(), str(t)) for t in tags if str(t).strip()]
    return " · ".join(labels) if labels else "—"

# 旧ラベル（CLI・互換）
MEDIAN_PF = "損益比"
MEDIAN_TRADES = TRADES
MEDIAN_EXPECTANCY = EXPECTANCY

EXPERIMENT_DF_COLUMNS: dict[str, str] = {
    "strategy_id": "戦略",
    "strategy_summary": STRATEGY_SUMMARY,
    "strategy_category": STRATEGY_CATEGORY,
    "rank": STRATEGY_RANK,
    "metrics_note": METRICS_NOTE,
    "strategy": "戦略",
    "id": "戦略ID",
    "style": "スタイル",
    "expectancy_pct": EXPECTANCY,
    "profit_factor": PROFIT_FACTOR,
    "win_rate": WIN_RATE,
    "total_trades": TRADES,
    "max_drawdown_pct": MAX_DRAWDOWN,
    "n_tickers": "評価銘柄数",
    "total_return_pct": "総リターン（%）",
    "portfolio_return_pct": PORTFOLIO_RETURN,
    "avg_pnl_pct": EXPECTANCY,
    "segment": "市場区分",
    "sector_tse": "業種（TSE33）",
    "ticker": "銘柄コード",
    "name": "銘柄名",
    "cohort": "コホート",
    "cohort_kind": "集計種別",
    "cohort_label": "区分・業種",
    "cohort_key": "集計キー",
    "median_return_pct": "中央値リターン（%）",
    "rule_id": "ラボルール",
    "expectancy_pct_lab": EXPECTANCY,
    "window": "評価期間",
    "error": "エラー",
}

EXPERIMENT_SORT_OPTIONS: list[tuple[str, str]] = [
    ("portfolio_return_pct", PORTFOLIO_RETURN),
    ("expectancy_pct", EXPECTANCY),
    ("profit_factor", PROFIT_FACTOR),
    ("win_rate", WIN_RATE),
    ("total_trades", TRADES),
    ("max_drawdown_pct", MAX_DRAWDOWN),
]

EXPERIMENT_RANKING_COLUMNS: list[str] = [
    "rank",
    "strategy_id",
    "style",
    "strategy_category",
    "strategy_summary",
    "portfolio_return_pct",
    "expectancy_pct",
    "profit_factor",
    "win_rate",
    "total_trades",
    "max_drawdown_pct",
    "metrics_note",
]

CATALOG_SORT_OPTIONS: list[tuple[str, str]] = [
    ("profit_factor", PROFIT_FACTOR),
    ("total_return_pct", "総リターン（%）"),
    ("win_rate", "勝率"),
    ("total_trades", "取引数"),
]


def sort_option_label(options: list[tuple[str, str]], key: str) -> str:
    return dict(options).get(key, key)

# --- Help text (st.metric help= / CLI footnotes) ---

HELP_PROFIT_FACTOR = (
    "1銘柄のバックテストで、勝ちトレードの利益合計 ÷ 負けトレードの損失合計。"
    "1.0 ならトントン、1.05 超ならコスト込みでもプラス期待になりやすい。"
)

HELP_MEDIAN_PF = (
    "各銘柄の損益比を並べたときの **真ん中の値**。"
    "超大手1社や大負け銘柄にランキングが引っ張られにくく、"
    "「典型的な銘柄でどうか」を見る指標。TSE 実験の主な比較軸。"
)

HELP_MEAN_PF = (
    "各銘柄の損益比の **算術平均**。"
    "極端に良い／悪い銘柄の影響を受けやすい。中央値と併せて見る。"
)

HELP_PCT_PF_ABOVE_1 = (
    "損益比が 1.0 を超えた銘柄が、評価銘柄のうち何割か。"
    "「勝ち銘柄がどれだけ多いか」の割合。中央値の損益比とは別の見方。"
)

HELP_EXPECTANCY = "1トレードあたりの平均損益（%）。0超なら1回ごとの期待はプラス。"
HELP_WIN_RATE = "勝ちトレード ÷ 全トレード。"
HELP_MAX_DD = "資産ピークからの最大下落（%）。マイナスが大きいほど含み損が深い。"

METRIC_HELP_JA: dict[str, str] = {
    "PF": HELP_PROFIT_FACTOR,
    PROFIT_FACTOR: HELP_PROFIT_FACTOR,
    EXPECTANCY: HELP_EXPECTANCY,
    WIN_RATE: HELP_WIN_RATE,
    MAX_DRAWDOWN: HELP_MAX_DD,
    TRADES: "バックテスト期間中の売買回数。少なすぎると偶然の可能性。",
}

# --- 「儲かるか」早見表（ダッシュボード・docs 共通） ---

PROFIT_CHECK_COLUMNS = ["優先", "指標", "見る場所", "儲かる目安", "補足"]

PROFIT_CHECK_ROWS: list[tuple[str, str, str, str, str]] = [
    ("1", EXPECTANCY, "TSE 一覧 · 銘柄別", "0 より大", "1回あたりの損益期待"),
    ("2", PROFIT_FACTOR, "TSE 一覧", "1.05 以上目安", "勝ち÷負け"),
    ("3", WIN_RATE, "TSE 一覧 · 銘柄別", "参考", "高くても1回大負けで崩れることあり"),
    ("4", TRADES, "TSE 一覧", "十分な回数", "目安 100 回以上"),
    ("5", MAX_DRAWDOWN, "TSE 一覧 · 銘柄別", "許容内", "途中の最大下落"),
]

PROFIT_CHECK_SCENARIO_COLUMNS = ["やりたいこと", "まず見る指標", "次に見る"]

PROFIT_CHECK_SCENARIO_ROWS: list[tuple[str, str, str]] = [
    (
        "この戦略を1銘柄（例 7203.T）で使う？",
        "総リターン · 損益比 · 取引数",
        "資産曲線 · Max DD",
    ),
    (
        "東証全銘柄で戦略を比較（TSE 実験）",
        f"{EXPECTANCY} · {PROFIT_FACTOR}",
        "戦略詳細 → 銘柄別",
    ),
    (
        "イザナミラボのルール",
        "期待値（%）",
        "損益比 · 勝率",
    ),
    (
        "これから先の成績（forward）",
        "ペーパートレードの資産推移",
        "—",
    ),
]

PROFIT_CHECK_FOOTNOTE = (
    "**損益比だけ** では「いくら儲かるか」は分かりません。"
    "**総リターン** と **期待値%** をセットで確認してください。"
    "TSE 実験は銘柄ごとの BT の横並びで、1口座に全銘柄を載せた合計円ではありません。"
)


def profit_check_priority_df():
    import pandas as pd

    return pd.DataFrame(PROFIT_CHECK_ROWS, columns=PROFIT_CHECK_COLUMNS)


def profit_check_scenario_df():
    import pandas as pd

    return pd.DataFrame(PROFIT_CHECK_SCENARIO_ROWS, columns=PROFIT_CHECK_SCENARIO_COLUMNS)


def render_profit_check_guide(*, expanded: bool = True) -> None:
    """Streamlit: 儲かるかどうかの早見表."""
    import streamlit as st

    with st.expander("💰 儲かるかどうか — 見る指標（早見表）", expanded=expanded):
        st.markdown("コスト込みバックテストで **本当に増えるか** を確認するときの目安です。")
        st.dataframe(profit_check_priority_df(), width="stretch", hide_index=True)
        st.markdown("#### 場面別")
        st.dataframe(profit_check_scenario_df(), width="stretch", hide_index=True)
        st.markdown(PROFIT_CHECK_FOOTNOTE)


GLOSSARY_TSE_EXPERIMENTS: list[tuple[str, str]] = [
    (EXPECTANCY, HELP_EXPECTANCY),
    (PROFIT_FACTOR, HELP_PROFIT_FACTOR),
    (WIN_RATE, HELP_WIN_RATE),
    (TRADES, "期間中の売買回数。"),
    (MAX_DRAWDOWN, HELP_MAX_DD),
    (
        TSE_TABLE_NOTE,
        "3521銘柄それぞれでBTし、同じ指標を並べたときの真ん中の銘柄の値。",
    ),
]


def rename_experiment_columns(df):
    """Return a copy with Japanese column headers where mapped."""
    import pandas as pd

    if not isinstance(df, pd.DataFrame):
        return df
    mapping = {c: EXPERIMENT_DF_COLUMNS[c] for c in df.columns if c in EXPERIMENT_DF_COLUMNS}
    return df.rename(columns=mapping)


def format_median_pf_value(pf: float | None) -> str:
    if pf is None:
        return "—"
    return f"{float(pf):.2f}"
