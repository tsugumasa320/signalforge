"""Japanese labels and short explanations for backtest / experiment metrics."""

from __future__ import annotations

# --- Display names (UI・CLI) ---

PROFIT_FACTOR = "損益比"
PROFIT_FACTOR_LONG = "損益比（PF）"
MEDIAN_PF = "中央値の損益比"
MEAN_PF = "平均の損益比"
PCT_PF_ABOVE_1 = "損益比が1超の銘柄比率"

EXPERIMENT_DF_COLUMNS: dict[str, str] = {
    "strategy_id": "戦略",
    "style": "スタイル",
    "median_pf": MEDIAN_PF,
    "mean_pf": MEAN_PF,
    "pct_pf_gt_1": PCT_PF_ABOVE_1,
    "n_tickers": "評価銘柄数",
    "profit_factor": PROFIT_FACTOR,
    "win_rate": "勝率",
    "total_trades": "取引数",
    "total_return_pct": "総リターン（%）",
    "median_profit_factor": MEDIAN_PF,
    "mean_profit_factor": MEAN_PF,
    "pct_pf_above_1": PCT_PF_ABOVE_1,
    "segment": "市場区分",
    "sector_tse": "業種（TSE33）",
    "ticker": "銘柄コード",
    "name": "銘柄名",
}

EXPERIMENT_SORT_OPTIONS: list[tuple[str, str]] = [
    ("median_pf", f"{MEDIAN_PF}（おすすめ）"),
    ("mean_pf", MEAN_PF),
    ("pct_pf_gt_1", PCT_PF_ABOVE_1),
    ("n_tickers", "評価銘柄数"),
]

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
    "「勝ち銘柄がどれだけ多いか」の割合。中央値PFとは別の見方。"
)

METRIC_HELP_JA: dict[str, str] = {
    "PF": HELP_PROFIT_FACTOR,
    PROFIT_FACTOR: HELP_PROFIT_FACTOR,
    MEDIAN_PF: HELP_MEDIAN_PF,
    MEAN_PF: HELP_MEAN_PF,
    PCT_PF_ABOVE_1: HELP_PCT_PF_ABOVE_1,
    "Median PF": HELP_MEDIAN_PF,
    "Mean PF": HELP_MEAN_PF,
}

GLOSSARY_TSE_EXPERIMENTS: list[tuple[str, str]] = [
    (
        MEDIAN_PF,
        HELP_MEDIAN_PF.replace("**", ""),
    ),
    (
        MEAN_PF,
        HELP_MEAN_PF.replace("**", ""),
    ),
    (
        PCT_PF_ABOVE_1,
        HELP_PCT_PF_ABOVE_1.replace("**", ""),
    ),
    (
        "銘柄ごと BT",
        "1 戦略 × 1 銘柄で過去データを売買シミュレーション。"
        "TSE 実験は内国株式プール全銘柄に対してこれを繰り返し、あとで集計する。",
    ),
    (
        "市場区分",
        "プライム / スタンダード / グロースなど。同じ戦略でも市場によって成績が変わることがある。",
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
