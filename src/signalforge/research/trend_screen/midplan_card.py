"""図56「中期計画の達成可能性チェック」の半自動カード。

機械で埋められる定量・業種ヒントを先に埋め、残りは要確認フラグにする。
完全自動の市場規模・KPI分解はしない。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signalforge.config import data_dir
from signalforge.research.trend_screen.duke_fundamentals import evaluate_duke_fundamentals
from signalforge.research.trend_screen.fundamentals import AnnualPoint
from signalforge.research.trend_screen.load import load_annuals


# 業種別の粗いヒント（図56の「売上の種類」「KPI」下書き用）
_SECTOR_HINTS: dict[str, dict[str, str]] = {
    "情報・通信業": {
        "revenue_mix": "ストック（継続課金・通信）比率が高めになりやすい",
        "kpi": "契約数/MAU × ARPU、またはライセンス数 × 単価",
        "market": "DX・クラウド・通信関連の市場成長を中計資料で確認",
    },
    "電気機器": {
        "revenue_mix": "フロー（製品販売）中心が多い。保守・部材はストック寄り",
        "kpi": "出荷台数 × 単価、または稼働率 × キャパ",
        "market": "半導体・オート・産業機器など最終需要のサイクルを確認",
    },
    "サービス業": {
        "revenue_mix": "会員・サブスクならストック、単発案件ならフロー",
        "kpi": "顧客数 × 単価、または取扱高 × 手数料率",
        "market": "対象市場のTAM/成長率を中計・業界レポートで確認",
    },
    "小売業": {
        "revenue_mix": "フロー中心。定期便・PBはストック寄り",
        "kpi": "既存店売上 × 店舗数、客数 × 客単価",
        "market": "消費動向・出店計画の実現性を確認",
    },
    "医薬品": {
        "revenue_mix": "既存薬はストック寄り、新薬上市はフロー変動大",
        "kpi": "処方数 × 薬価、パイプライン進捗",
        "market": "適応疾患の患者数・競合・薬価改定リスクを確認",
    },
    "不動産業": {
        "revenue_mix": "賃貸はストック、売却益はフロー",
        "kpi": "稼働率 × 賃料、または売却件数 × 利益率",
        "market": "金利・需給・開発パイプラインを確認",
    },
}


@dataclass
class CheckItem:
    id: str
    label: str
    status: str  # auto_ok | auto_warn | needs_human | unknown
    detail: str = ""


@dataclass
class MidplanCard:
    ticker: str
    code: str
    name: str
    sector: str
    as_of: str
    checks: list[CheckItem] = field(default_factory=list)
    fund_summary: dict[str, Any] = field(default_factory=dict)
    targets: dict[str, Any] = field(default_factory=dict)
    kpi_template: str = ""
    revenue_mix_hint: str = ""
    market_hint: str = ""
    human_todos: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "code": self.code,
            "name": self.name,
            "sector": self.sector,
            "as_of": self.as_of,
            "checks": [asdict(c) for c in self.checks],
            "fund_summary": self.fund_summary,
            "targets": self.targets,
            "kpi_template": self.kpi_template,
            "revenue_mix_hint": self.revenue_mix_hint,
            "market_hint": self.market_hint,
            "human_todos": self.human_todos,
            "notes": self.notes,
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        }


def sector_hints(sector: str) -> dict[str, str]:
    if not sector:
        return {
            "revenue_mix": "ストック/フロー比率は有報・説明資料で確認",
            "kpi": "事業ごとのドライバー（顧客数×単価など）を中計から抽出",
            "market": "市場規模・成長率は業界レポート／中計で確認",
        }
    for key, val in _SECTOR_HINTS.items():
        if key in sector:
            return val
    return {
        "revenue_mix": f"{sector}: ストック/フローの構成比を中計・有報で確認",
        "kpi": "セグメント別に『数量×単価』または『取扱高×料率』へ分解",
        "market": "対象市場の規模・成長・自社シェアの根拠を中計で確認",
    }


def _hint(sector: str) -> dict[str, str]:
    return sector_hints(sector)


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.1%}"


def build_midplan_card(
    *,
    ticker: str,
    name: str = "",
    sector: str = "",
    price: float | None = None,
    annuals: list[AnnualPoint] | None = None,
    box_height: float | None = None,
) -> MidplanCard:
    code = ticker.replace(".T", "")
    if annuals is None:
        try:
            annuals, _src = load_annuals(ticker, refresh=False)
        except Exception:
            annuals = []
    fund = evaluate_duke_fundamentals(annuals, price=price, box_height=box_height)
    hints = _hint(sector)
    as_of = datetime.now(timezone.utc).astimezone().date().isoformat()

    checks = [
        CheckItem(
            "market_size",
            "市場規模（パイの大きさ）",
            "needs_human",
            hints["market"] + "（機械では業界TAMを確定できない）",
        ),
        CheckItem(
            "market_growth",
            "市場成長率",
            "auto_ok" if fund.gates.get("fund_sales_up") else "auto_warn",
            (
                f"自社売上YoY {_pct(fund.sales_yoy)} は市場成長の代理ではない。"
                "市場自体の拡大/縮小は中計・業界統計で要確認。"
            ),
        ),
        CheckItem(
            "share",
            "獲得シェアとその根拠",
            "needs_human",
            "競合比較・シェア数値は公開APIでは不足。中計・IRのシェア記述を確認。",
        ),
        CheckItem(
            "revenue_mix",
            "売上の種類（ストック/フロー）",
            "needs_human",
            hints["revenue_mix"],
        ),
        CheckItem(
            "sales_trend",
            "売上の伸び（通期）",
            "auto_ok" if fund.gates.get("fund_sales_up") else ("unknown" if not fund.has_data else "auto_warn"),
            f"売上YoY {_pct(fund.sales_yoy)}",
        ),
        CheckItem(
            "op_trend",
            "営業利益の伸び（通期）",
            "auto_ok" if fund.gates.get("fund_op_up") else ("unknown" if not fund.has_data else "auto_warn"),
            f"営業利益YoY {_pct(fund.op_yoy)} / 利益率 {_pct(fund.op_margin)}（変化 {_pct(fund.op_margin_delta)}）",
        ),
        CheckItem(
            "target_vs_price",
            "粗いファンダ目標 vs 現値",
            "auto_ok" if fund.gates.get("fund_upside_pos") else ("unknown" if fund.target_price_fund is None else "auto_warn"),
            (
                f"目標 {fund.target_price_fund:.0f} / 現値 {price:.0f} / 上振れ {_pct(fund.upside_pct)}"
                if fund.target_price_fund and price
                else "目標未算出"
            ),
        ),
    ]

    human_todos = [
        "中期経営計画で市場規模・成長率・シェア目標を抜き出す",
        f"KPIを『{hints['kpi']}』の形に落とす（CHANGE例: 顧客数×単価 / 取扱高×手数料率）",
        "ストック売上比率と、フロー依存のリスクを確認する",
        "達成前提（採用・単価・規制・為替）が崩れたときの損切り条件を決める",
    ]

    return MidplanCard(
        ticker=ticker,
        code=code,
        name=name or code,
        sector=sector or "未確認",
        as_of=as_of,
        checks=checks,
        fund_summary={
            "sales_yoy": fund.sales_yoy,
            "op_yoy": fund.op_yoy,
            "op_margin": fund.op_margin,
            "eps": fund.eps,
            "fwd_eps": fund.fwd_eps,
            "assumed_per": fund.assumed_per,
            "trailing_per": fund.trailing_per,
        },
        targets={
            "price": price,
            "stop": fund.stop_price,
            "t1": fund.t1_price,
            "t2": fund.t2_price,
            "t3": fund.t3_price,
            "fund": fund.target_price_fund,
            "upside_pct": fund.upside_pct,
            "box_height": box_height,
        },
        kpi_template=hints["kpi"],
        revenue_mix_hint=hints["revenue_mix"],
        market_hint=hints["market"],
        human_todos=human_todos,
        notes=list(fund.notes)
        + ["図56の市場・シェア・KPIは人手確認が必須。本カードは下書き。"],
    )


def card_path(ticker: str) -> Path:
    return data_dir() / "reports" / "trend_screen" / "midplan" / f"{ticker.replace('/', '_')}.json"


def save_midplan_card(card: MidplanCard, path: Path | None = None) -> Path:
    path = path or card_path(card.ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def format_midplan_text(card: MidplanCard) -> str:
    lines = [
        f"# 中計チェックカード {card.code} {card.name}",
        f"業種: {card.sector} · 作成日: {card.as_of}",
        "",
        "## 自動チェック",
    ]
    for c in card.checks:
        mark = {"auto_ok": "OK", "auto_warn": "注意", "needs_human": "要確認", "unknown": "不明"}.get(
            c.status, c.status
        )
        lines.append(f"- [{mark}] {c.label}: {c.detail}")
    lines.extend(
        [
            "",
            "## 目標株価（粗い）",
            f"- 現値: {card.targets.get('price')}",
            f"- 損切: {card.targets.get('stop')} / T1: {card.targets.get('t1')} / "
            f"T2(ボックス): {card.targets.get('t2')} / T3: {card.targets.get('t3')}",
            f"- ファンダ目標: {card.targets.get('fund')}（上振れ {card.targets.get('upside_pct')}）",
            "",
            "## 人手TODO（図56）",
            *[f"- {t}" for t in card.human_todos],
            "",
            f"KPIテンプレ: {card.kpi_template}",
            f"売上構成ヒント: {card.revenue_mix_hint}",
        ]
    )
    return "\n".join(lines)
