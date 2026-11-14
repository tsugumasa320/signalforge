"""採用した長期トレンド・シストレ規則。

改善レースで確認を通った案があれば data/trend_screen/system/adopted.json を優先する。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from signalforge.research.trend_screen.config import (
    MA200_SLOPE_LAG,
    MA75_SLOPE_LAG,
    RET_1Y_STEPS,
    RET_3Y_STEPS,
    ROUND_TRIP_COST,
)

DEFAULT_SYSTEM_ID = "trend_primary_top5_1y"
DEFAULT_SYSTEM_VERSION = "1.0"
DEFAULT_SYSTEM_NAME = "長期上昇トレンド・1年リターン上位5"


@dataclass(frozen=True)
class SystemRules:
    id: str = DEFAULT_SYSTEM_ID
    version: str = DEFAULT_SYSTEM_VERSION
    name: str = DEFAULT_SYSTEM_NAME
    universe: str = "liquid_turnover_top"
    universe_limit: int = 300
    require_above_ma200: bool = True
    ma200_slope_lag: int = MA200_SLOPE_LAG
    ma75_slope_lag: int = MA75_SLOPE_LAG
    ret_1y_steps: int = RET_1Y_STEPS
    ret_3y_steps: int = RET_3Y_STEPS
    require_topix_excess_1y: bool = True
    benchmark: str = "1306.T"
    rank_by: str = "ret_1y"
    top_n: int = 5
    weight: str = "equal"
    sector_max: int | None = None
    min_turnover: float | None = None
    min_ret_20d: float | None = None
    require_above_ma25: bool = False
    max_dd_52w: float | None = None
    signal_on: str = "month_end"
    entry: str = "next_session_close"
    exit: str = "next_month_signal_next_session_close"
    round_trip_cost: float = ROUND_TRIP_COST
    unused: tuple[str, ...] = (
        "地合いフィルター（1306の200日線）",
        "押し目・PPPのみのエントリー",
        "毎日判定・毎日リバランス",
        "該当銘柄の全数等金額",
        "1銘柄集中",
        "業績・PEGフィルター（学習期間で測れず）",
    )


def adopted_path() -> Path:
    from signalforge.config import data_dir

    return data_dir() / "trend_screen" / "system" / "adopted.json"


def load_adopted() -> SystemRules:
    base = SystemRules()
    path = adopted_path()
    if not path.exists():
        return base
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return base
    return replace(
        base,
        id=str(payload.get("system_id") or base.id),
        version=str(payload.get("version") or base.version),
        name=str(payload.get("name") or base.name),
        top_n=int(payload.get("top_n") or base.top_n),
        rank_by=str(payload.get("rank_by") or base.rank_by),
        weight=str(payload.get("weight") or base.weight),
        sector_max=payload.get("sector_max", base.sector_max),
        min_turnover=payload.get("min_turnover", base.min_turnover),
        min_ret_20d=payload.get("min_ret_20d", base.min_ret_20d),
        require_above_ma25=bool(payload.get("require_above_ma25", base.require_above_ma25)),
        max_dd_52w=payload.get("max_dd_52w", base.max_dd_52w),
    )


# 後方互換。実行時は load_adopted() を使う。
ADOPTED = SystemRules()
SYSTEM_ID = DEFAULT_SYSTEM_ID
SYSTEM_VERSION = DEFAULT_SYSTEM_VERSION
SYSTEM_NAME = DEFAULT_SYSTEM_NAME


def rules_markdown(rules: SystemRules | None = None) -> str:
    rules = rules or load_adopted()
    rank_label = {
        "ret_1y": "過去1年の株価リターン",
        "risk_adj_1y": "過去1年リターン÷1年ボラ",
    }.get(rules.rank_by, rules.rank_by)
    weight_label = {
        "equal": "等金額",
        "inv_vol": "1年ボラの逆数ウェイト",
    }.get(rules.weight, rules.weight)
    lines = [
        f"# {rules.name}",
        "",
        f"- ID: `{rules.id}` / 版 {rules.version}",
        "",
        "## ユニバース",
        "",
        f"- 東証プライム・スタンダード・グロースの普通株",
        f"- 直近20営業日の終値×出来高平均が上位 {rules.universe_limit}",
        "",
        "## 銘柄の一次条件（日足・すべて必須）",
        "",
        "1. 終値 > 200日移動平均",
        f"2. 200日線が {rules.ma200_slope_lag} 営業日前より高い",
        f"3. 75日線が {rules.ma75_slope_lag} 営業日前より高い",
        f"4. 過去約1年（{rules.ret_1y_steps}営業日）の株価リターン > 0",
        f"5. 過去約3年（{rules.ret_3y_steps}営業日）の株価リターン > 0",
        f"6. 過去約1年で {rules.benchmark}（TOPIX連動ETF）を上回る",
        "",
        "## 選定と保有",
        "",
        f"- ランキング: {rank_label}",
        f"- 上位 {rules.top_n} 銘柄",
        f"- 配分: {weight_label}",
    ]
    if rules.sector_max is not None:
        lines.append(f"- 同一33業種は最大 {rules.sector_max} 銘柄")
    if rules.min_turnover is not None:
        lines.append(f"- 20日売買代金が {rules.min_turnover:,.0f} 円以上")
    if rules.min_ret_20d is not None:
        lines.append(f"- 過去20営業日の株価リターンが {rules.min_ret_20d:.0%} 超")
    if rules.require_above_ma25:
        lines.append("- 終値が25日移動平均より上")
    if rules.max_dd_52w is not None:
        lines.append(f"- 52週高値からの下落が {rules.max_dd_52w:.0%} より浅い（例: -15%なら高値から15%以内）")
    lines.extend(
        [
            "",
            "## カレンダー",
            "",
            "- 毎月末の終値で判定",
            "- 翌営業日の終値でリバランス",
            "- 次の月末判定の翌営業日まで保有",
            "",
            "## 検証時のコスト",
            "",
            f"- 入れ替え割合に対して往復 {rules.round_trip_cost:.1%}",
            "",
            "## 採用しなかったもの",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in rules.unused)
    lines.append("")
    return "\n".join(lines)
