"""仮説の配点と閾値。過去成績で検証するまで確定しない。"""

from __future__ import annotations

METHOD_VERSION = "1.0"
PRICE_START = "2016-01-01"
RET_1Y_STEPS = 245
RET_3Y_STEPS = 735
MA_WINDOWS = (5, 25, 75, 200)
MA200_SLOPE_LAG = 60
MA75_SLOPE_LAG = 20
MA_SHORT_SLOPE_LAG = 5
LIQUIDITY_YEN = 50_000_000
ROUND_TRIP_COST = 0.002
FORWARD_HORIZONS = (21, 63, 126, 245)
TOP_N = 30
DETAIL_N = 10

CHART_MAX = {
    "ret_3y": 8.0,
    "ret_1y": 6.0,
    "ma200_slope": 6.0,
    "ma75_slope": 4.0,
    "above_ma200": 6.0,
    "mdd_3y": 10.0,
    "mdd_1y": 4.0,
    "excess_1y": 4.0,
    "up_months": 2.0,
}
FUND_MAX = {
    "sales": 7.0,
    "op": 7.0,
    "eps": 7.0,
    "opm": 4.0,
    "roe": 4.0,
    "ocf": 3.0,
    "equity": 3.0,
}
VALUATION_MAX = 15.0
# 予想PEGが無いとき、信頼性の3点は加点しない。
HISTORICAL_VALUATION_MAX = 12.0

# 自己資本比率の一律基準を当てはめない33業種。
EQUITY_RATIO_EXEMPT = (
    "銀行業",
    "保険業",
    "その他金融業",
    "証券、商品先物取引業",
    "不動産業",
    "卸売業",
)

WEIGHTS_NOTE = (
    "チャート50・業績35・バリュエーション15は仮説。"
    "過去データで検証するまで、配点と判定閾値は確定ではない。"
)

CHART_LABELS = {
    "ret_3y": "3年リターン",
    "ret_1y": "1年リターン",
    "ma200_slope": "200日線の傾き",
    "ma75_slope": "75日線の傾き",
    "above_ma200": "200日線より上の日数",
    "mdd_3y": "3年最大ドローダウン",
    "mdd_1y": "1年最大ドローダウン",
    "excess_1y": "TOPIX相対（1年）",
    "up_months": "上昇月の割合",
}

UNCONFIRMED_ALWAYS = (
    "特別利益・一時的な為替差益と本業利益の分離",
    "市場予想（コンセンサス）",
    "会社の業績予想",
    "有利子負債の推移",
    "直近四半期の成長鈍化（評価は通期のみ）",
)
