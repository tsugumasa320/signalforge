"""Frozen rules for the STF momentum study.

These constants were set before any backtest result was inspected.
Do not retune them to improve a reported number. Sensitivities belong
in ``sensitivity_specs`` and must be labeled as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Requested window. The live API plan may cover only a subset.
WARMUP_START = date(2016, 11, 1)
EVAL_START = date(2017, 3, 1)
EVAL_END = date(2025, 12, 31)

INITIAL_CAPITAL = 10_000_000.0

TOP_N = 20
NAME_CAP = 0.10
LIQUIDITY_JPY = 50_000_000.0  # 20-bar average yen turnover
STOP_DEFAULT = -0.05
FEE = 0.0015  # one way
SLIPPAGE = 0.0005  # one way
FINANCE_RATE = 0.02  # annual, actual/365, on negative cash
DELIST_PENALTY = 0.01  # extra haircut vs last close; not a TOB model
MIN_WARM_NAMES = 50  # data gate, not a ranking parameter

# Domestic cash equity sections. Post-2022 names plus the pre-restructuring
# sections so a later full-history download does not silently drop 2017–2022.
TSE_CASH_MARKETS = frozenset(
    {
        "0101",  # 東証一部
        "0102",  # 東証二部
        "0104",  # マザーズ
        "0106",  # JASDAQスタンダード
        "0107",  # JASDAQグロース
        "0111",  # プライム
        "0112",  # スタンダード
        "0113",  # グロース
    }
)
COMMON_STOCK = "011"  # ProdCat. ETFs are 014, REITs and others differ.

# Official /indices/bars/daily/topix is not on the current plan.
# 13060 is NEXT FUNDS TOPIX (1306). Split-adjusted price, not the official index.
BENCHMARK_CODE = "13060"

# Fixed before results. Not a complete semiconductor universe.
SEMI_CODES = frozenset(
    {
        "80350",  # 東京エレクトロン
        "68570",  # アドバンテスト
        "69200",  # レーザーテック
        "61460",  # ディスコ
        "67230",  # ルネサス
        "34360",  # SUMCO
        "77350",  # SCREEN
        "65250",  # KOKUSAI ELECTRIC
        "69630",  # ローム
        "40620",  # イビデン
        "40040",  # レゾナック
        "41860",  # 東京応化工業
    }
)
ELEC_SECTOR = "電気機器"

# Score = 0.5 * rel20 + 0.5 * rel60.
# Tie-break: higher rel60, higher 20-day yen turnover, then ascending code.
SCORE_W20 = 0.5
SCORE_W60 = 0.5


@dataclass(frozen=True)
class StrategySpec:
    name: str
    weighting: str  # "equal" or "score"
    leverage: float
    overlay: bool
    top_n: int = TOP_N
    stop: float | None = STOP_DEFAULT
    name_cap: float = NAME_CAP
    score_mode: str = "blend"  # blend, rel20, rel60
    rel_filter: str = "both"  # both, rel20, rel60
    require_slope: bool = True
    fee: float = FEE
    slippage: float = SLIPPAGE
    finance: float = FINANCE_RATE
    min_adv: float = LIQUIDITY_JPY
    min_price: float = 0.0
    max_ret60: float | None = None
    markets: frozenset[str] | None = None
    max_per_sector: int | None = None
    regime_sma: int | None = None
    earnings_mode: str | None = None  # drop_cut, raise_first, raise_only

    @property
    def one_way(self) -> float:
        return self.fee + self.slippage


def base_specs() -> list[StrategySpec]:
    """A–E exactly as specified. A/B do not use the overlay or the stop."""
    return [
        StrategySpec("A_equal_1x", "equal", 1.0, False, stop=None),
        StrategySpec("B_score_1x", "score", 1.0, False, stop=None),
        StrategySpec("C_score_overlay_1x", "score", 1.0, True, stop=-0.05),
        StrategySpec("D_score_overlay_1_5x", "score", 1.5, True, stop=-0.05),
        StrategySpec("E_score_overlay_2x", "score", 2.0, True, stop=-0.05),
    ]


def sensitivity_specs() -> list[StrategySpec]:
    """Phase-4 variants. Not used to replace the base result."""
    c = dict(weighting="score", leverage=1.0, overlay=True, stop=-0.05)
    a = dict(weighting="equal", leverage=1.0, overlay=False, stop=None)
    out = [
        StrategySpec("C_stop_3", **{**c, "stop": -0.03}),
        StrategySpec("C_stop_8", **{**c, "stop": -0.08}),
        StrategySpec("C_stop_10", **{**c, "stop": -0.10}),
        StrategySpec("C_stop_none", **{**c, "stop": None}),
        StrategySpec("C_n10", **{**c, "top_n": 10}),
        StrategySpec("C_n30", **{**c, "top_n": 30}),
        StrategySpec("C_n50", **{**c, "top_n": 50}),
        StrategySpec("A_n10", **{**a, "top_n": 10}),
        StrategySpec("A_n30", **{**a, "top_n": 30}),
        StrategySpec("A_n50", **{**a, "top_n": 50}),
        StrategySpec("C_score_rel20", **{**c, "score_mode": "rel20"}),
        StrategySpec("C_score_rel60", **{**c, "score_mode": "rel60"}),
        StrategySpec("C_no_slope", **{**c, "require_slope": False}),
        StrategySpec("C_zero_cost", **{**c, "fee": 0.0, "slippage": 0.0, "finance": 0.0}),
        StrategySpec(
            "E_zero_cost",
            weighting="score",
            leverage=2.0,
            overlay=True,
            stop=-0.05,
            fee=0.0,
            slippage=0.0,
            finance=0.0,
        ),
        StrategySpec(
            "E_high_cost",
            weighting="score",
            leverage=2.0,
            overlay=True,
            stop=-0.05,
            fee=0.003,
            slippage=0.001,
            finance=0.03,
        ),
    ]
    return out


PRIME = frozenset({"0111"})
# A forecast change older than this many sessions is treated as stale.
GUIDANCE_LOOKBACK = 63


def improvement_specs() -> list[StrategySpec]:
    """Revisions after the 2025 loss. Not a replacement for A–E.

    The filters are the ones already used for live-like entries in this
    project (Prime, 5億円 turnover) plus the same 75-day trend rule applied
    to the benchmark. They were not searched to maximize 2025.
    """
    quality = dict(
        weighting="equal",
        leverage=1.0,
        overlay=False,
        stop=None,
        min_adv=500_000_000.0,
        min_price=500.0,
        markets=PRIME,
        max_per_sector=3,
        top_n=20,
    )
    return [
        StrategySpec("F_prime_liquid", **quality),
        StrategySpec("G_prime_regime", **quality, regime_sma=75),
        StrategySpec("H_prime_overlay", **{**quality, "overlay": True, "stop": -0.08}),
        StrategySpec("I_prime_n30_regime", **{**quality, "top_n": 30, "regime_sma": 75}),
        StrategySpec("J_prime_skip20", **{**quality, "score_mode": "skip20", "regime_sma": 75}),
    ]


def earnings_specs() -> list[StrategySpec]:
    """G plus one earnings rule. Thresholds were not searched on 2025."""
    quality = dict(
        weighting="equal",
        leverage=1.0,
        overlay=False,
        stop=None,
        min_adv=500_000_000.0,
        min_price=500.0,
        markets=PRIME,
        max_per_sector=3,
        top_n=20,
        regime_sma=75,
    )
    return [
        StrategySpec("G_drop_cut", **quality, earnings_mode="drop_cut"),
        StrategySpec("G_raise_first", **quality, earnings_mode="raise_first"),
        StrategySpec("G_raise_only", **quality, earnings_mode="raise_only"),
    ]


def known_limitations() -> list[str]:
    return [
        "配当金をリターンに含めていない。fins/dividend は現在のプランで 403。",
        "公式TOPIX（/indices/bars/daily/topix）は現在のプランで 403。相対強度とベンチマークはTOPIX連動ETF 1306（コード13060）の調整済終値。",
        "1306は分配落ちで価格が下がる。配当なしTOPIXよりベンチマークが低くなり、超過リターンを過大に見せうる。",
        "株価APIの契約期間が約2年のため、2017年3月〜2024年夏は未検証。サバイバーシップを避ける過去ユニバースは、取得できた期間の月末マスターに限る。",
        "シグナルは当日終値まで。約定は翌営業日の始値。同日終値での約定はしない。",
        "25日線・75日線・5本前比較・20/60日リターンは、その銘柄の足が存在する本数で計算する。停止日は本数に数えない。",
        "損切りと移動平均の判定は終値のみ。場中の安値では切らない。",
        "単元株、信用規制、貸借銘柄限定、ストップ高安による約定不能、追証、税金は再現していない。",
        "上場廃止・TOB・合併の対価は再現していない。最終足の翌営業日に、最終終値から手数料・スリッページに加え1%を控除して現金化する。",
        "信用金利は借入（現金がマイナスの額）に年率2%を actual/365 で日割り。銘柄ごとの実勢金利ではない。",
        "指標を計算できるユニバース銘柄が50未満の月末は、データ不足として発注しない。",
        "等金額は、選ばれた銘柄数 k（最大20）で100%を分割する。スコア配分はスコア比例のあと1銘柄10%を上限に再配分し、上限で余った分は現金。レバレッジはそのウェイト列に倍率を掛ける。",
        "オーバレイは月中だけ。25日線割れで当月目標の半分を一度だけ、75日線割れまたは買値から-5%で全売却。回復しても次回の月末まで戻さない。月末に選ばれ、かつ既存建玉が損切り幅に達している銘柄は継続保有しない。",
    ]
