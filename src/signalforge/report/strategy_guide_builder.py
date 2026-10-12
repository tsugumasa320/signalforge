"""Build per-strategy guide content for all catalog IDs (template + params → 日本語解説)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

from signalforge.config import load_implementation_map, load_web_catalog

SWING_EXIT = [
    "利確: ATR × 3.0（style 設定）",
    "損切: ATR × 1.5",
    "最大保有: 15 本（日足）",
    "トレーリングストップ: ATR × 2.0（有効時）",
    "約定: 翌日寄り付き（next_day_open）",
]

DAYTRADE_EXIT = [
    "利確: ATR × 2.0 / 損切: ATR × 1.0",
    "最大保有: 12 本（5 分足）",
    "15:55 強制決済（セッション終了）",
]

STYLE_LABEL = {
    "swing": "スイング（日足）",
    "daytrade": "デイトレ（5分足）",
    "swing_high_winrate": "スイング・高勝率",
    "swing_champion": "Champion プリセット",
}


def _col_label(col: str) -> str:
    mapping = {
        "ema5": "EMA5",
        "ema20": "EMA20",
        "ema25": "EMA25",
        "ema50": "EMA50",
        "ema75": "EMA75",
        "ema200": "EMA200",
    }
    return mapping.get(col, col.upper() if col.startswith("ema") else col)


def _format_params(params: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in params.items():
        out[k] = str(v)
    return out


def _entries_ma_cross(p: dict[str, Any]) -> tuple[list[str], str | None, list[str]]:
    fast = _col_label(str(p.get("fast", "ema20")))
    slow = _col_label(str(p.get("slow", "ema50")))
    direction = p.get("direction", "golden")
    long_only = p.get("long_only", True)
    trend = p.get("trend_col")
    long_rules = [f"前足: {fast} ≤ {slow} → 当足: {fast} > {slow}（ゴールデンクロス）"]
    if trend:
        long_rules.append(f"終値 > {_col_label(str(trend))}（トレンドフィルタ）")
    buy = f"{fast}/{slow} ゴールデンクロスで **買い**"
    short_rules: list[str] = []
    sell = None
    if direction == "dead" or not long_only:
        short_rules = [f"{fast}/{slow} デッドクロスで **売り（ショート）**"]
        sell = f"{fast}/{slow} デッドクロス"
    elif direction == "dead" and long_only:
        buy = None
    return long_rules, sell, short_rules if short_rules else ["ロング専用設定時はショートなし"]


_TEMPLATE_BUILDERS: dict[str, Callable[[dict[str, Any], str | None], dict[str, Any]]] = {}


def _register(name: str):
    def deco(fn):
        _TEMPLATE_BUILDERS[name] = fn
        return fn

    return deco


@_register("ma_cross")
def _guide_ma_cross(p: dict, approx: str | None) -> dict[str, Any]:
    long_r, sell, short_r = _entries_ma_cross(p)
    return {
        "concept": "短期・長期移動平均のクロスでトレンド転換または追随を狙う定番ロジックです。",
        "entry_long": long_r,
        "signal_buy": long_r[0] if long_r else "—",
        "signal_sell": sell,
        "entry_short": short_r,
        "market": "トレンドが続く相場向き。レンジではダマシが増えます。",
    }


@_register("perfect_order_pullback")
def _guide_perfect_order(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "EMA5 > EMA25 > EMA75 のパーフェクトオーダー上で、EMA25 への押し目から反発したら買います。",
        "entry_long": [
            "EMA5 > EMA25 > EMA75（上昇パーフェクトオーダー）",
            "安値が EMA25 付近までタッチし、終値が EMA25 上で引け",
        ],
        "signal_buy": "パーフェクトオーダー上の EMA25 押し目 **買い**",
        "signal_sell": None,
        "entry_short": ["なし（ロング）"],
        "market": "中〜長期上昇トレンドの日本株スイング向け。",
    }


@_register("rsi_oversold")
def _guide_rsi_oversold(p: dict, approx: str | None) -> dict[str, Any]:
    rsi_max = p.get("rsi_max", 30)
    reclaim = p.get("rsi_reclaim", rsi_max)
    ema200 = p.get("require_ema200", False)
    rules = [f"前足 RSI < {rsi_max} → 当足 RSI ≥ {reclaim}（売られ過ぎからの戻り）"]
    if ema200:
        rules.append("終値 > EMA200")
    return {
        "concept": "RSI の売られ過ぎ圏からのリクレイムを短期底打ちシグナルとみなします。",
        "entry_long": rules,
        "signal_buy": "RSI リクレイム **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "調整後の反発。下落トレンドでは慎重に。",
    }


@_register("rsi_momentum")
def _guide_rsi_momentum(p: dict, approx: str | None) -> dict[str, Any]:
    rsi_min = p.get("rsi_min", 60)
    ema = _col_label(str(p.get("ema_col", "ema25")))
    sig = p.get("signal", "long")
    return {
        "concept": "RSI が強い水準を維持し、価格が短期 EMA 上にある「強いモメンタム」に乗ります。",
        "entry_long": [f"RSI ≥ {rsi_min}", f"終値 > {ema}"] if sig == "long" else ["—"],
        "signal_buy": f"RSI モメンタム + {ema} 上 **買い**" if sig == "long" else None,
        "signal_sell": f"RSI ≥ {rsi_min} でショートカバー/売りシグナル" if sig == "exit_short" else None,
        "entry_short": [],
        "market": "トレンド加速局面。",
    }


@_register("mean_reversion_rsi")
def _guide_mean_rev(p: dict, approx: str | None) -> dict[str, Any]:
    d = _guide_rsi_oversold({"rsi_max": 35, "rsi_reclaim": 35, **p}, approx)
    d["concept"] = "RSI による平均回帰（35 割れからの戻り）を狙う逆張り寄りロジックです。"
    return d


@_register("bb_rsi")
def _guide_bb_rsi(p: dict, approx: str | None) -> dict[str, Any]:
    side = p.get("side", "lower")
    if side == "lower":
        return {
            "concept": "ボリンジャー下限付近かつ RSI 売られ過ぎで反発を狙います。",
            "entry_long": [
                f"終値 ≤ BB 下限",
                f"RSI ≤ {p.get('rsi_max', 30)}",
            ],
            "signal_buy": "BB 下限 + RSI 売られ過ぎ **買い**",
            "signal_sell": None,
            "entry_short": ["なし"],
            "market": "レンジ〜弱い上昇の押し目。",
        }
    return {
        "concept": "BB 上限 + RSI 買われ過ぎでショートまたは利確シグナル。",
        "entry_long": [],
        "signal_buy": None,
        "signal_sell": f"BB 上限 + RSI ≥ {p.get('rsi_min', 70)}",
        "entry_short": [f"終値 ≥ BB 上限", f"RSI ≥ {p.get('rsi_min', 70)}"],
        "market": "過熱感のある上昇後。",
    }


@_register("volume_breakout")
def _guide_vol_break(p: dict, approx: str | None) -> dict[str, Any]:
    vr = p.get("volume_ratio_min", 1.5)
    return {
        "concept": "出来高急増を伴う前日高値ブレイクで初動を狙います。",
        "entry_long": [
            f"出来高比率 ≥ {vr}（20 本平均比）",
            "終値 > 前日高値",
        ],
        "signal_buy": "出来高ブレイク **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "材料・需給の入った日。",
    }


@_register("donchian_breakout")
def _guide_donchian(p: dict, approx: str | None) -> dict[str, Any]:
    period = p.get("period", 20)
    return {
        "concept": f"ドンチャン {period} 日高値ブレイク（タートル系）でトレンド追随。",
        "entry_long": [f"終値 > 過去 {period} 日高値（前足基準）"],
        "signal_buy": "ドンチャンブレイク **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "トレンド発生〜継続期。",
    }


@_register("adx_trend")
def _guide_adx(p: dict, approx: str | None) -> dict[str, Any]:
    adx = p.get("adx_min", 25)
    ema = _col_label(str(p.get("ema_col", "ema50")))
    return {
        "concept": "ADX でトレンドの強さを確認し、価格が EMA 上にあるときだけ買います。",
        "entry_long": [f"ADX ≥ {adx}", f"終値 > {ema}"],
        "signal_buy": f"ADX トレンド + {ema} 上 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "トレンド相場。ADX 低いレンジではシグナル少。",
    }


@_register("momentum_ema")
def _guide_mom_ema(p: dict, approx: str | None) -> dict[str, Any]:
    ema = _col_label(str(p.get("ema_col", "ema20")))
    return {
        "concept": f"終値が {ema} 上かつ前足より上昇した「単純モメンタム」追随。",
        "entry_long": [f"終値 > {ema}", "終値 > 前日終値"],
        "signal_buy": f"{ema} 上の陽線 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "緩やかな上昇。ノイズも多い。",
    }


@_register("high_breakout_rsi")
def _guide_high_br(p: dict, approx: str | None) -> dict[str, Any]:
    lb = p.get("lookback", 126)
    rsi_min = p.get("rsi_min", 60)
    return {
        "concept": f"約 {lb} 日高値圏付近で RSI が {rsi_min} 以上＝高値圏での強さを確認して買い。",
        "entry_long": [
            f"終値 ≥ 過去 {lb} 日高値の 98%",
            f"RSI ≥ {rsi_min}",
        ],
        "signal_buy": "高値圏モメンタム **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "新高値更新トレンド。",
    }


@_register("gap_up")
def _guide_gap_up(p: dict, approx: str | None) -> dict[str, Any]:
    g = float(p.get("min_gap_pct", 0.01)) * 100
    return {
        "concept": "ギャップアップ後に陽線で終わる日の初動を狙います。",
        "entry_long": [f"寄り付きギャップ ≥ {g:.1f}%", "終値 > 始値（陽線）"],
        "signal_buy": "ギャップアップ **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "好材料・指数ギャップ日。",
    }


@_register("gap_fill_reversal")
def _guide_gap_fill(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "ギャップダウン後、前日終値まで戻して陽線で引けた反発を狙います。",
        "entry_long": ["寄り付き < 前日終値", "日中に前日終値まで回復", "陽線引け"],
        "signal_buy": "ギャップフィル反発 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "過度なギャップダウン後の戻り。",
    }


@_register("macd_histogram_reversal")
def _guide_macd_hist(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "MACD ヒストグラムがマイナス圏からプラスに転じ、MACD > シグナルのとき買い。",
        "entry_long": [
            "ヒストグラム: 前足 < 0 → 当足 > 0",
            "MACD > シグナル",
        ],
        "signal_buy": "MACD ヒストグラム反転 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "下落からの V 反転初期。",
    }


@_register("combo_macd_rsi")
def _guide_combo_mr(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "MACD ゴールデンクロスに RSI 帯域（45〜70）と EMA50 上を組み合わせたフィルタ付き MACD。",
        "entry_long": [
            "MACD ゴールデンクロス",
            "45 ≤ RSI ≤ 70",
            "終値 > EMA50",
        ],
        "signal_buy": "MACD + RSI 帯 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "トレンド中の過熱しすぎない MACD エントリー。",
    }


@_register("combo_macd_rsi_ichimoku")
def _guide_combo_ichi(p: dict, approx: str | None) -> dict[str, Any]:
    base = _guide_combo_mr(p, approx)
    base["concept"] = base["concept"] + " さらに終値が一目雲（スパンA/B 上側）上であることを要求します。"
    base["entry_long"] = base["entry_long"] + ["終値 > 雲の上（スパンA/B 最大値）"]
    return base


@_register("ema200_filter_macd")
def _guide_ema200_macd(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "MACD ゴールデンクロスを EMA200 上の銘柄に限定した長期上昇トレンド追随。",
        "entry_long": ["MACD ゴールデンクロス", "終値 > EMA200"],
        "signal_buy": "EMA200 上 MACD **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "長期上昇銘柄の MACD エントリー。",
    }


@_register("kairi_mean_reversion")
def _guide_kairi(p: dict, approx: str | None) -> dict[str, Any]:
    ema = _col_label(str(p.get("ema_col", "ema25")))
    k = p.get("kairi_max_pct", -2.0)
    return {
        "concept": f"終値の {ema} からの乖離率（乖離率）が {k}% 以下の押し過ぎからの反発。",
        "entry_long": [f"乖離率 ≤ {k}%（{ema} 基準）", "トレンド EMA フィルタ（設定時）"],
        "signal_buy": "乖離率戻り **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "短期売られ過ぎの大型株など。",
    }


@_register("three_bar_reversal")
def _guide_three_bar(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "3 本連続で高値更新後の陰線を弱気反転（ショート）シグナルとみなすパターン。",
        "entry_long": [],
        "signal_buy": None,
        "signal_sell": "3 本高値更新後の陰線 **売り**",
        "entry_short": ["高値 3 本切り上げ → 当足陰線"],
        "market": "短期天井警戒。",
    }


@_register("heikin_ashi_trend")
def _guide_ha(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "平均足（Heikin-Ashi）が 2 本連続で陽線のトレンド追随。",
        "entry_long": ["HA 陽線 2 本連続"],
        "signal_buy": "HA トレンド **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "ノイズ除去後のトレンド。",
    }


@_register("ichimoku_kumo_break")
def _guide_ichi_kumo(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "終値が一目均衡表の雲（スパンA/B）を上抜けた初動を買い。",
        "entry_long": ["前足: 終値 ≤ 雲上限 → 当足: 終値 > 雲上限"],
        "signal_buy": "雲ブレイク **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "トレンド転換〜加速。",
    }


@_register("ichimoku_sanyaku")
def _guide_ichi_san(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "三役好転（転換 > 基準、終値 > 雲、終値 > 転換）に相当する条件を機械化。",
        "entry_long": [
            "転換線 > 基準線",
            "終値 > 雲上限",
            "終値 > 転換線",
        ],
        "signal_buy": "三役好転型 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "一目強気配置。",
    }


@_register("ichimoku_tk_cross")
def _guide_ichi_tk(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "転換線が基準線を上抜け（TK ゴールデンクロス）で買い。",
        "entry_long": ["転換線 ゴールデンクロス 基準線"],
        "signal_buy": "TK クロス **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "短期トレンド転換。",
    }


@_register("ichimoku_kijun_pullback")
def _guide_ichi_kijun(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "雲の上で基準線への押し目から反発したら買い。",
        "entry_long": [
            "安値 ≤ 基準線 ≤ 終値（基準線タッチ反発）",
            "終値 > 雲上限",
        ],
        "signal_buy": "基準線押し目 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "一目トレンド中の押し目。",
    }


@_register("cci_cross")
def _guide_cci(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "CCI が 0 線を下から上抜けしたタイミングで買い。",
        "entry_long": ["前足 CCI < 0 → 当足 CCI ≥ 0"],
        "signal_buy": "CCI 0 線クロス **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "モメンタム転換。",
    }


@_register("swing_pullback_ema")
def _guide_pullback_ema(p: dict, approx: str | None) -> dict[str, Any]:
    ema = _col_label(str(p.get("ema_col", "ema20")))
    return {
        "concept": f"安値が {ema} にタッチし、終値が {ema} 上で引けた押し目買い。",
        "entry_long": [f"安値 ≤ {ema}", f"終値 > {ema}"],
        "signal_buy": f"{ema} 押し目 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "上昇トレンドの押し目。",
    }


@_register("bb_squeeze_proxy")
def _guide_bb_sq(p: dict, approx: str | None) -> dict[str, Any]:
    return {
        "concept": "BB 幅が収縮（スクイーズ）した後、終値が BB ミドル上で拡大開始した方向を買い。",
        "entry_long": [
            "BB 幅 < 過去20本平均（スクイーズ）",
            "終値 > BB ミドル",
        ],
        "signal_buy": "スクイーズ解除 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "ボラティリティ拡大前夜。",
    }


@_register("vwap_proxy_daily")
def _guide_vwap_proxy(p: dict, approx: str | None) -> dict[str, Any]:
    mode = p.get("mode", "pullback")
    approx_note = f"（注: {approx}）" if approx else ""
    if mode == "pullback":
        return {
            "concept": f"日足上で VWAP（無い場合 EMA20）への押し目からの反発を近似{approx_note}。",
            "entry_long": ["安値 ≤ VWAP/EMA20", "終値 > VWAP/EMA20"],
            "signal_buy": "VWAP 押し目 **買い**",
            "signal_sell": None,
            "entry_short": ["なし"],
            "market": "デイトレ VWAP ロジックの日足近似。",
        }
    if mode == "mean_rev_short":
        return {
            "concept": f"VWAP 下でショートシグナル（日足近似）{approx_note}。",
            "entry_long": [],
            "signal_buy": None,
            "signal_sell": "終値 < VWAP **売り**",
            "entry_short": ["終値 < VWAP/EMA20"],
            "market": "弱気 VWAP 下。",
        }
    return {
        "concept": f"VWAP 上ブレイク + 陽線（日足近似）{approx_note}。",
        "entry_long": ["終値 > VWAP/EMA20", "終値 > 前日終値"],
        "signal_buy": "VWAP 上 **買い**",
        "signal_sell": None,
        "entry_short": ["なし"],
        "market": "VWAP 追随。",
    }


@_register("ema_pullback_proxy")
def _guide_ema_pb_proxy(p: dict, approx: str | None) -> dict[str, Any]:
    return _guide_pullback_ema({"ema_col": "ema20"}, approx)


@lru_cache(maxsize=1)
def _catalog_index() -> dict[str, dict[str, Any]]:
    return {
        str(s["id"]): s
        for s in load_web_catalog().get("strategies", [])
        if s.get("id")
    }


@lru_cache(maxsize=1)
def _impl_index() -> dict[str, dict[str, Any]]:
    return dict(load_implementation_map().get("strategies") or {})


def _catalog_entry(strategy_id: str) -> dict[str, Any] | None:
    return _catalog_index().get(strategy_id)


def _deep_guides() -> dict[str, Any]:
    from signalforge.report.dashboard_strategies import STRATEGY_GUIDES

    return STRATEGY_GUIDES


@lru_cache(maxsize=256)
def resolve_strategy_guide(strategy_id: str) -> dict[str, Any]:
    """Full StrategyGuide dict for dashboard (deep manual or generated from template)."""
    deep_guides = _deep_guides()
    cat = _catalog_entry(strategy_id) or {}
    if strategy_id in deep_guides:
        guide = dict(deep_guides[strategy_id])
        if cat.get("sources") and not guide.get("sources"):
            guide["sources"] = cat["sources"]
        return guide

    impl = _impl_index().get(strategy_id) or {}
    style_key = cat.get("style") or impl.get("catalog_style") or "swing"
    style_label = STYLE_LABEL.get(str(style_key), str(style_key))
    title = cat.get("name") or strategy_id
    params = dict(impl.get("params") or {})
    approx = impl.get("approximation")

    if impl.get("builtin"):
        # Should be covered by deep_guides; fallback minimal
        return {
            "title": title,
            "style": style_label,
            "summary": f"組み込み実装 `{impl['builtin']}`。詳細はコード / 深いガイドを参照。",
            "concept": "—",
            "entry_long": ["（組み込み戦略 — テンプレート解説なし）"],
            "signal_buy": "—",
            "signal_sell": None,
            "entry_short": ["—"],
            "exit": DAYTRADE_EXIT if style_key == "daytrade" else SWING_EXIT,
            "params": _format_params(params),
            "market": "—",
            "pros": ["実装済み"],
            "cons": ["—"],
            "tips": "TSE 実験タブで全銘柄の「中央値の損益比」を確認。",
        }

    template = impl.get("template")
    if template == "builtin_macd":
        template = "ema200_filter_macd"
        params = {**params, **impl.get("params", {})}

    body: dict[str, Any] = {}
    if template and template in _TEMPLATE_BUILDERS:
        body = _TEMPLATE_BUILDERS[template](params, approx)
    else:
        body = {
            "concept": "カタログテンプレート（要確認）。",
            "entry_long": ["implementation_map.yaml を参照"],
            "signal_buy": "—",
            "signal_sell": None,
            "entry_short": ["—"],
            "market": "—",
        }

    summary = body.get("concept", "")[:120]
    if approx:
        summary = f"{summary} 【近似実装: {approx}】"

    tags = cat.get("tags") or []
    return {
        "title": title,
        "style": style_label,
        "summary": summary,
        "concept": body.get("concept", ""),
        "entry_long": body.get("entry_long") or ["条件はテンプレート参照"],
        "signal_buy": body.get("signal_buy"),
        "signal_sell": body.get("signal_sell"),
        "entry_short": body.get("entry_short") or ["なし"],
        "exit": DAYTRADE_EXIT if style_key == "daytrade" else SWING_EXIT,
        "params": {**_format_params(params), "template": template or "—", **({} if not approx else {"approximation": approx})},
        "market": body.get("market", "—"),
        "pros": ["カタログ出典に基づくルール", "全 TSE 銘柄で同一条件 BT 可能"],
        "cons": ["テンプレート近似の戦略は原手法と差がある場合あり" if approx else "パラメータ感度あり"],
        "tips": (
            f"タグ: {', '.join(tags) if tags else '—'}。"
            "参考リンクはページ下部の「参考ソース」を展開。"
            " Streamlit ダッシュボードの 📚 戦略解説タブでも同内容を閲覧できます。"
        ),
        "sources": cat.get("sources") or [],
    }


def strategy_display_title(strategy_id: str) -> str:
    return str(resolve_strategy_guide(strategy_id).get("title") or strategy_id)
