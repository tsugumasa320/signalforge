"""Short Japanese rule text for diversified paper pages.

Buy conditions follow ``catalog_template`` plus ``implementation_map.yaml``.
Exit numbers follow that map's ``exit:`` block, otherwise the swing style
defaults that ``pipeline._apply_strategy_exit`` leaves in place.
``BacktestEngine`` reads ATR take-profit, ATR stop, and max hold only
(``swing.yaml`` ``trailing_stop_atr`` is unused). Account gates follow
``DEFAULT_ENTRY_RULES`` and ``simulate_diversified_portfolio``.
"""

from __future__ import annotations

import inspect
from dataclasses import fields
from html import escape
from typing import Any

from signalforge.config import load_implementation_map, load_style_config, load_web_catalog
from signalforge.data.entry_filters import EARNINGS_BLACKOUT_DAYS, uses_reversion_entry
from signalforge.indicators.engine import adx, atr, bollinger, cci, rsi
from signalforge.lab.portfolio_sim import DEFAULT_ENTRY_RULES, simulate_diversified_portfolio
from signalforge.paper.diversified import DiversifiedPaperBook
from signalforge.portfolio.entry_features import attach_breadth, attach_turnover

_LONG_ONLY = frozenset(
    {
        "bb_rsi",
        "mean_reversion_rsi",
        "rsi_oversold",
        "cci_cross",
        "ichimoku_tk_cross",
        "adx_trend",
    }
)


def _num(value: object) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _yen_floor(value: float) -> str:
    if value >= 1e8 and abs(value / 1e8 - round(value / 1e8)) < 1e-6:
        return f"{int(round(value / 1e8))}億円"
    return f"{value:,.0f}円"


def _ema_span(col: object) -> str:
    name = str(col or "ema50")
    rest = name[3:] if name.startswith("ema") else ""
    return rest if rest.isdigit() else name


def _catalog_name(strategy_id: str) -> str:
    for row in load_web_catalog().get("strategies") or []:
        if str(row.get("id") or "") == strategy_id:
            return str(row.get("name") or "")
    return ""


def _spec(strategy_id: str) -> dict[str, Any]:
    raw = (load_implementation_map().get("strategies") or {}).get(strategy_id) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _signal_params(template: str, params: dict[str, Any]) -> dict[str, Any]:
    """Mirror default merges in ``catalog_template`` (map params win)."""
    merged = dict(params or {})
    if template == "mean_reversion_rsi":
        merged = {"rsi_max": 35, "rsi_reclaim": 35, **merged}
    if template in ("mean_reversion_rsi", "rsi_oversold"):
        rsi_max = float(merged.get("rsi_max", 30))
        merged["rsi_max"] = rsi_max
        merged["rsi_reclaim"] = float(merged.get("rsi_reclaim", rsi_max))
        merged["require_ema200"] = bool(merged.get("require_ema200", False))
    if template == "bb_rsi":
        merged["side"] = merged.get("side", "lower")
        merged["rsi_max"] = float(merged.get("rsi_max", 30))
    if template == "adx_trend":
        merged["adx_min"] = float(merged.get("adx_min", 25))
        merged["ema_col"] = merged.get("ema_col", "ema50")
    return merged


def _position_defaults() -> tuple[int, float]:
    found = {item.name: item.default for item in fields(DiversifiedPaperBook)}
    return int(found["max_positions"]), float(found["position_pct"])


def _exit_numbers(strategy_id: str, style: str) -> tuple[float, float, int, bool, float, float, int]:
    """Actual TP, SL, hold, whether the map overrides, then swing-style defaults."""
    style_cfg = load_style_config(style)
    style_exit = dict((style_cfg.get("rules") or {}).get("exit") or {})
    style_tp = float(style_exit.get("atr_tp_multiple", 3.0))
    style_sl = float(style_exit.get("atr_sl_multiple", 1.5))
    style_hold = int((style_cfg.get("backtest") or {}).get("max_hold_bars") or style_exit.get("max_hold_bars") or 15)
    override = dict(_spec(strategy_id).get("exit") or {})
    tp = float(override.get("atr_tp_multiple", style_tp))
    sl = float(override.get("atr_sl_multiple", style_sl))
    hold = int(override.get("max_hold_bars", style_hold))
    return tp, sl, hold, bool(override), style_tp, style_sl, style_hold


def _buy_rule(template: str, params: dict[str, Any]) -> str:
    rsi_period = int(inspect.signature(rsi).parameters["period"].default)
    bb_period = int(inspect.signature(bollinger).parameters["period"].default)
    bb_std = float(inspect.signature(bollinger).parameters["std"].default)
    adx_period = int(inspect.signature(adx).parameters["period"].default)
    cci_period = int(inspect.signature(cci).parameters["period"].default)

    if template == "bb_rsi" and params.get("side") == "lower":
        return (
            f"当日の終値がボリンジャーバンド下限（{bb_period}日移動平均から{_num(bb_std)}標準偏差下）以下で、"
            f"かつRSI({rsi_period})が{_num(params['rsi_max'])}以下の日に買います。"
            "下抜けた日だけではなく、条件を満たす日は毎日シグナルが出ます。"
        )
    if template in ("mean_reversion_rsi", "rsi_oversold"):
        lo = _num(params["rsi_max"])
        hi = _num(params["rsi_reclaim"])
        text = f"RSI({rsi_period})が前の足で{lo}未満、当足で{hi}以上に戻った日に買います。"
        if params.get("require_ema200"):
            text += "終値がEMA200より上であることも必要です。"
        return text
    if template == "cci_cross":
        return (
            f"CCI({cci_period})が前の足では0未満、当足では0以上になった日に買います。"
        )
    if template == "ichimoku_tk_cross":
        return (
            "転換線（過去9日の高値と安値の中値）が基準線（過去26日）を、"
            "前の足では基準線以下、当足では基準線より上へ抜けた日に買います。"
            "雲の上かどうかは見ていません。"
        )
    if template == "adx_trend":
        return (
            f"ADX({adx_period})が{_num(params['adx_min'])}以上で、"
            f"当日の終値がEMA{_ema_span(params['ema_col'])}より上の日に買います。"
            "クロスした日だけではなく、条件を満たす日は毎日シグナルが出ます。"
        )
    if template:
        return f"テンプレート {template} の条件で買います。"
    return "implementation_map に買い条件がありません。"


def _entry_title_gap(strategy_id: str, title: str, template: str) -> str:
    if strategy_id == "mean_reversion_short_term" and template == "mean_reversion_rsi" and "5日" in title:
        return (
            "カタログ名は「短期リバーサル（過去5日リターン逆張り）」ですが、"
            "コードは過去5日のリターンを計算していません。"
        )
    if strategy_id == "cci_zero_cross" and template == "cci_cross" and "100" in title:
        return (
            "カタログ名は「CCI ゼロライン / ±100 ブレイク」ですが、"
            "±100のブレイクは条件にありません。0ラインの上抜けだけです。"
        )
    if strategy_id == "rsi_dip_200ma" and template == "rsi_oversold" and "割れ" in title:
        return (
            "カタログ名は「RSI35割れ」ですが、RSIが35未満のあいだは買わず、"
            "35以上へ戻った足だけが買いです。"
        )
    if (
        strategy_id == "bnf_regime_trend_vs_fade"
        and template == "adx_trend"
        and ("逆張り" in title or "切替" in title)
    ):
        return (
            "カタログ名は「上げ相場順張り / 下げ相場逆張り切替」ですが、"
            "地合いを見て逆張りに切り替える処理はありません。"
        )
    return ""


def _exit_title_gap(strategy_id: str, title: str, template: str) -> str:
    if strategy_id == "trailing_atr_chandelier" and template == "adx_trend" and "シャンデリア" in title:
        return (
            "カタログ名は「ATR / シャンデリアエグジット」ですが、"
            "シャンデリア（直近高値からATRを引く追跡損切り）は使っていません。"
        )
    return ""


def _fill_sentence(style: str) -> str:
    fill = str((load_style_config(style).get("backtest") or {}).get("fill") or "")
    if fill == "next_day_open":
        return "条件が揃った翌セッションの寄り付きで買います。"
    if fill:
        return f"約定方法は {fill} です。"
    return ""


def _earnings_sentence(strategy_id: str) -> str:
    if uses_reversion_entry(strategy_id):
        return (
            f"決算発表日の前後{EARNINGS_BLACKOUT_DAYS}日（発表当日を含む、暦日）はシグナルを消します。"
        )
    return "決算発表日の前後ではシグナルを消しません。"


def _buy_paragraph(strategy_id: str, style: str) -> str:
    spec = _spec(strategy_id)
    template = str(spec.get("template") or "")
    params = _signal_params(template, dict(spec.get("params") or {}))
    parts = [_buy_rule(template, params)]
    if template in _LONG_ONLY and not (
        template == "bb_rsi" and params.get("side") == "upper" and params.get("signal") == "short"
    ):
        parts.append("空売りシグナルはありません。")
    parts.append(
        "判定に使う指標は、その足の終値を含めない1本前の確定値です。"
        "終値・高値・安値はその日の足です。"
    )
    fill = _fill_sentence(style)
    if fill:
        parts.append(fill)
    parts.append(_earnings_sentence(strategy_id))
    gap = _entry_title_gap(strategy_id, _catalog_name(strategy_id), template)
    if gap:
        parts.append(gap)
    return "".join(parts)


def _exit_paragraph(strategy_id: str, style: str) -> str:
    tp, sl, hold, overridden, style_tp, style_sl, style_hold = _exit_numbers(strategy_id, style)
    atr_period = int(inspect.signature(atr).parameters["period"].default)
    spec = _spec(strategy_id)
    template = str(spec.get("template") or "")
    gap = _exit_title_gap(strategy_id, _catalog_name(strategy_id), template)
    if overridden:
        source = (
            "決済幅はこの戦略だけの上書きで、"
            f"スイング既定（利確ATR×{_num(style_tp)}、損切りATR×{_num(style_sl)}、最大{style_hold}本）ではありません。"
        )
    else:
        source = "この戦略に決済の上書きはありません。決済幅はスイング既定です。"
    mechanics = (
        f"高値が、約定価格にその足のATR({atr_period})の{_num(tp)}倍を足した値以上なら利確します。"
        f"そこまで届かず、安値が約定価格からATR({atr_period})の{_num(sl)}倍を引いた値以下なら損切りします。"
        "ATRも1本前の確定値です。"
        f"{hold}本経過しても届かなければ、その足の翌寄りで売ります。"
        "シグナルが消えただけでは売りません。"
    )
    return "".join(part for part in (gap, source, mechanics) if part)


def _account_paragraph(
    *,
    max_positions: int,
    position_pct: float,
    entry_rules: dict[str, Any],
) -> str:
    breadth_window = int(inspect.signature(attach_breadth).parameters["window"].default)
    min_history = int(inspect.signature(attach_breadth).parameters["min_history"].default)
    turnover_window = int(inspect.signature(attach_turnover).parameters["window"].default)
    max_per_sector = int(inspect.signature(simulate_diversified_portfolio).parameters["max_per_sector"].default)
    priority = str(entry_rules.get("entry_priority") or "")
    turnover = float(entry_rules.get("min_turnover_jpy") or 0)
    breadth = float(entry_rules.get("min_breadth_rank") or 0)
    regime = str(entry_rules.get("regime_filter") or "none")
    pct = int(round(float(position_pct) * 100))
    parts = [f"1口座で同時に最大{max_positions}銘柄、1件あたりはその時点の現金の{pct}%。"]
    if priority == "sector_turnover":
        cap = ""
        if priority.startswith("sector_"):
            cap = f"業種が付いている銘柄は、同じ東証業種を同時に最大{max_per_sector}銘柄までです。"
        parts.append(
            f"同じ日に候補が複数なら、直近{turnover_window}日の平均売買代金"
            f"（終値×出来高、エントリーより前）が大きい順に採用します。{cap}"
        )
    elif priority.startswith("sector_"):
        parts.append(
            f"同じ日の優先順は{priority}です。"
            f"業種が付いている銘柄は、同じ東証業種を同時に最大{max_per_sector}銘柄までです。"
        )
    elif priority:
        parts.append(f"同じ日の優先順は{priority}です。")
    if turnover > 0:
        parts.append(f"その{turnover_window}日平均が{_yen_floor(turnover)}未満の銘柄は買いません。")
    if breadth > 0:
        rank_pct = int(round(breadth * 100))
        top_pct = int(round((1.0 - breadth) * 100))
        parts.append(
            f"買う日は、この戦略自身のシグナル本数を直近{breadth_window}エントリー日と比べ、"
            f"本数がより少なかった日の割合が{rank_pct}%以上の日だけです"
            f"（おおよそ本数が多い上位{top_pct}%）。"
            f"比べられる過去のエントリー日が{min_history}日未満の日は買いません。"
            "これは指数の暴落を見る条件ではありません。"
        )
    if regime == "none":
        parts.append("日経連動ETFの200日線や急落では買いを止めません。")
    else:
        parts.append(f"地合いフィルタは{regime}です。")
    return "".join(parts)


def explain_diversified_strategy(
    strategy_id: str,
    *,
    style: str = "swing",
    max_positions: int | None = None,
    position_pct: float | None = None,
    entry_rules: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Plain Japanese paragraphs: buy, exit, shared account gates."""
    default_positions, default_pct = _position_defaults()
    rules = dict(DEFAULT_ENTRY_RULES if entry_rules is None else entry_rules)
    return {
        "buy": _buy_paragraph(strategy_id, style),
        "exit": _exit_paragraph(strategy_id, style),
        "account": _account_paragraph(
            max_positions=default_positions if max_positions is None else int(max_positions),
            position_pct=default_pct if position_pct is None else float(position_pct),
            entry_rules=rules,
        ),
    }


def diversified_strategy_rules_html(
    strategy_id: str,
    *,
    style: str = "swing",
    max_positions: int | None = None,
    position_pct: float | None = None,
    entry_rules: dict[str, Any] | None = None,
) -> str:
    text = explain_diversified_strategy(
        strategy_id,
        style=style,
        max_positions=max_positions,
        position_pct=position_pct,
        entry_rules=entry_rules,
    )
    return (
        '<section class="strategy-rules">'
        "<h2>この戦略のルール</h2>"
        f"<p><strong>いつ買うか。</strong> {escape(text['buy'])}</p>"
        f"<p><strong>いつ手じまうか。</strong> {escape(text['exit'])}</p>"
        f"<p><strong>口座の共通条件。</strong> {escape(text['account'])}</p>"
        "</section>"
    )
