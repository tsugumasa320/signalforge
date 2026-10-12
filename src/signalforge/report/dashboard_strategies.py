"""Detailed strategy guide for the Streamlit dashboard (Japanese)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from signalforge.config import load_web_catalog
from signalforge.report.strategy_guide_builder import resolve_strategy_guide
from signalforge.report.strategy_visuals import plot_strategy_demo, render_check_legend

SIGNAL_LEGEND = "▲ 緑 = 買いシグナル　▼ 赤 = 売りシグナル（図はイメージ）"

StrategyGuide = dict[str, Any]

STRATEGY_GUIDES: dict[str, StrategyGuide] = {
    "macd_cross": {
        "title": "MACD クロス",
        "style": "スイング（日足）",
        "styles": ["swing", "swing_high_winrate"],
        "summary": "MACD がシグナル線を上抜け（ゴールデンクロス）したタイミングで、上昇トレンド中の買いを狙うモメンタム戦略。",
        "concept": (
            "MACD（Moving Average Convergence Divergence）は、短期・長期の指数移動平均の差と"
            "その平滑化線（シグナル）を使い、トレンド転換や勢いの変化を捉えます。"
            "ゴールデンクロス＝短期勢いが長期を上回った瞬間を「買いの合図」とみなします。"
        ),
        "entry_long": [
            "前足: MACD ≤ シグナル → 当足: MACD > シグナル（ゴールデンクロス）",
            "終値 > トレンド EMA（デフォルト EMA50、最適化時 EMA200）",
            "ADX > 閾値（任意。最適化プリセットでは ADX > 23 でトレンド相場のみ）",
            "RSI・出来高比率・EMA200・MACD ヒストグラムなどの追加フィルタ（設定次第）",
        ],
        "signal_buy": "上昇トレンド中に MACD がシグナル線を上抜けたら **買い（ロング）**",
        "signal_sell": "下降トレンド中に MACD がシグナル線を下抜けたら **売り（ショート）** ※ `long_only=true` では無効",
        "entry_short": [
            "デッドクロス（MACD がシグナルを下抜け）かつ終値 < トレンド EMA",
            "`long_only: true` の場合はショートなし（swing_high_winrate プリセット等）",
        ],
        "exit": [
            "利確: エントリー価格 + ATR × 2.0〜3.0",
            "損切: エントリー価格 − ATR × 1.5",
            "最大保有: 12〜15 本（日足）",
            "トレーリングストップ: ATR × 2.0（設定あり）",
        ],
        "params": {
            "ema_trend": "トレンド判定に使う EMA 期間（50 または 200）",
            "adx_min": "ADX 下限。0 = フィルタなし、23 = トレンドがはっきりした局面のみ",
            "long_only": "ロングのみ（ショート禁止）",
            "rsi_min / rsi_max": "RSI 帯域フィルタ（任意）",
            "volume_ratio_min": "出来高が平均の何倍以上か（任意）",
        },
        "market": "明確な上昇トレンドが続く相場（日本株の材料株・指数上昇局面など）。レンジ相場ではダマシが増えます。",
        "pros": ["ルールが明確で再現しやすい", "ADX・EMA でダマシを減らせる", "最適化パラメータあり（サイドバー）"],
        "cons": ["横ばい相場ではシグナルが多く PF が落ちやすい", "遅行指標のため天井付近エントリーになり得る"],
        "tips": "サイドバーの「macd_cross 最適化パラメータ」を ON にすると ADX>23・EMA200・ATR 利確/損切の調整版を使用します。"
        " swing_high_winrate スタイルはこの戦略 + ML フィルタの組み合わせです。",
    },
    "ema_pullback": {
        "title": "EMA 押し目買い",
        "style": "スイング（日足）",
        "styles": ["swing"],
        "summary": "長期上昇トレンド（EMA200 上）で、短期 EMA20 まで押し目が来たら買い。トレンドフォローの定番。",
        "concept": (
            "「上昇している株は押し目で買う」というトレンドフォロー思想。"
            "EMA200 で大きな方向を確認し、EMA20 付近までの調整を待ってからエントリーします。"
        ),
        "entry_long": [
            "終値 > EMA200（長期上昇トレンド）",
            "安値が EMA20 付近までタッチ（low ≤ EMA20 × 1.002）",
            "終値 > EMA20（押し目後に反発して終わっている）",
            "ADX > 25（トレンドの強さ確認）",
        ],
        "signal_buy": "EMA200 上の上昇トレンドで EMA20 押し目から反発したら **買いのみ**",
        "signal_sell": None,
        "entry_short": ["なし（ロング専用）"],
        "exit": [
            "利確: ATR × 3.0",
            "損切: ATR × 1.5",
            "最大保有: 15 本（日足）",
            "トレーリングストップ: ATR × 2.0",
        ],
        "params": {
            "rules.long": "YAML の long ルール一覧（adx 閾値など）",
            "exit.atr_tp_multiple": "利確幅（ATR の倍数）",
            "exit.max_hold_bars": "最大保有足数",
        },
        "market": "緩やか〜中程度の上昇トレンド。急落・暴落局面では EMA 割れが連続しやすい。",
        "pros": ["理屈がわかりやすい", "勝率が比較的安定しやすい", "日本株スイング向き"],
        "cons": ["強いトレンドでは押し目が浅くエントリー機会が少ない", "レンジ相場では EMA 付近で往復しやすい"],
        "tips": "ML フィルタと組み合わせると、押し目シグナルの質をさらに絞り込めます。",
    },
    "ma_golden_cross": {
        "title": "EMA 5-25 ゴールデンクロス",
        "style": "スイング（日足）",
        "styles": ["swing"],
        "summary": "短期 EMA5 が EMA25 を上抜け、かつ EMA75 上でトレンド方向に乗る日本株でよく紹介されるパターン。",
        "concept": "5日・25日・75日移動平均の順序（パーフェクトオーダー）や短期クロスを、トレンドフィルタ付きで機械化した戦略です。",
        "entry_long": [
            "EMA5 が EMA25 を上抜け（ゴールデンクロス）",
            "終値 > EMA75",
            "ADX 閾値（任意）",
        ],
        "signal_buy": "EMA5/25 ゴールデンクロス + EMA75 上 **買い**",
        "signal_sell": "EMA5/25 デッドクロス + EMA75 下 **売り**（long_only 時は無効）",
        "entry_short": ["デッドクロスかつ EMA75 下"],
        "exit": ["swing デフォルト: ATR 利確/損切・最大保有 15 日"],
        "params": {"adx_min": "トレンド強度フィルタ", "long_only": "ロングのみ"},
        "market": "トレンドが続く大型・中型株。レンジではダマシが増えます。",
        "pros": ["ルールが単純", "日本のテクニカル解説と相性が良い"],
        "cons": ["遅行性", "横ばい相場向きではない"],
        "tips": "`uv run signalforge scan --strategy ma_golden_cross` でユニバース横断評価。",
    },
    "rsi_reversal": {
        "title": "RSI 売られ過ぎ反発",
        "style": "スイング（日足）",
        "styles": ["swing"],
        "summary": "RSI が売られ過ぎ圏から戻ったタイミングで、EMA200 上の銘柄を買う逆張り寄りのセット。",
        "concept": "RSI 30 割れからのリクレイム（30 上抜け）を「短期の底打ちシグナル」とみなし、長期トレンド方向に限定します。",
        "entry_long": [
            "前足 RSI < 30 → 当足 RSI ≥ 30",
            "終値 > EMA200（任意）",
        ],
        "signal_buy": "RSI リクレイム **買い**",
        "signal_sell": None,
        "entry_short": ["long_only 時はなし"],
        "exit": ["swing デフォルト exit ルール"],
        "params": {"rsi_oversold": "売られ過ぎ閾値", "require_ema200": "長期上昇トレンド限定"},
        "market": "調整後の反発を狙う局面。暴落トレンドでは連続損切りに注意。",
        "pros": ["エントリー理由が明確", "ブログ・YouTube で解説が多い"],
        "cons": ["下落トレンドでは早すぎる拾いになりやすい"],
        "tips": "Web 出典一覧: `uv run signalforge strategies catalog`",
    },
    "bb_squeeze": {
        "title": "ボリンジャー・スクイーズ",
        "style": "スイング（日足）",
        "styles": ["swing"],
        "summary": "ボリンジャーバンド幅が歴史的に狭い（スクイーズ）状態から、上下どちらかへブレイクした方向に乗る。",
        "concept": (
            "ボラティリティが収縮したあとは拡大（方向性のある動き）が起きやすい、という考え方。"
            "バンド幅のパーセンタイルが 20% 未満＝「エネルギーが溜まっている」とみなします。"
        ),
        "entry_long": [
            "BB 幅パーセンタイル < 20（スクイーズ状態）",
            "終値が BB 上限を上抜け（前足は上限以下）",
        ],
        "signal_buy": "スクイーズ後に **上限ブレイク** → 買い（上方向への初動）",
        "signal_sell": "スクイーズ後に **下限ブレイク** → 売り（下方向への初動）",
        "entry_short": [
            "スクイーズ状態から BB 下限を下抜け",
        ],
        "exit": [
            "利確: ATR × 3.0 / 損切: ATR × 1.5（swing デフォルト）",
            "最大保有: 15 本",
        ],
        "params": {
            "bb_width percentile": "過去データに対する BB 幅の相対的な狭さ（20 未満 = スクイーズ）",
        },
        "market": "ボラティリティが一度縮小したあとのブレイク局面。決算前後や大型イベント前後に出やすい。",
        "pros": ["大きな値動きの初動を狙える", "ロング・ショート両対応"],
        "cons": ["ダマシブレイク（フェイクアウト）が多い", "スクイーズ判定が厳しくシグナル数が少ない"],
        "tips": "「全戦略を比較」で macd_cross や ema_pullback と PF・Max DD を並べて確認するのがおすすめです。",
    },
    "vwap_ema": {
        "title": "VWAP + EMA クロス",
        "style": "デイトレ（5分足）",
        "styles": ["daytrade"],
        "summary": "VWAP（出来高加重平均）の上下で方向を決め、EMA9/21 のクロスと出来高急増でエントリー。",
        "concept": (
            "VWAP は「その日の平均的な約定コスト」。機関投資家も参照する基準線で、"
            "価格が VWAP より上＝買い優勢、下＝売り優勢と解釈します。"
            "EMA クロスで短期の勢いの転換を確認します。"
        ),
        "entry_long": [
            "終値 > VWAP（買い優勢ゾーン）",
            "EMA9 が EMA21 を上抜け（ゴールデンクロス）",
            "出来高 > 20 本平均の 1.5 倍",
        ],
        "signal_buy": "VWAP より上で EMA9 が EMA21 を上抜け、出来高急増 → **買い**",
        "signal_sell": "VWAP より下で EMA9 が EMA21 を下抜け、出来高急増 → **売り**",
        "entry_short": [
            "終値 < VWAP",
            "EMA9 が EMA21 を下抜け",
            "出来高 > 平均の 1.5 倍",
        ],
        "exit": [
            "利確: ATR × 2.0 / 損切: ATR × 1.0",
            "最大保有: 12 本（5分足 ≒ 1 時間）",
            "15:55 強制決済（引け前フラット）",
        ],
        "params": {
            "volume multiplier": "1.5 倍（出来高確認）",
            "session": "09:30〜15:55（米国市場）",
        },
        "market": "トレンドがはっきりした日（VWAP から離れて推移）。薄商い・レンジ日は不利。",
        "pros": ["デイトレの定番ロジック", "VWAP で方向の軸が明確", "当日決済でオーバーナイトリスクなし"],
        "cons": ["5分足データは yfinance だと約 60 日分のみ", "スリッページの影響が大きい"],
        "tips": "長期デイトレ BT には `.env` に Alpaca API キーを設定してデータを取得してください。",
    },
    "vwap_reclaim": {
        "title": "VWAP リクレイム",
        "style": "デイトレ（5分足）",
        "styles": ["daytrade"],
        "summary": "VWAP から大きく乖離（ストレッチ）したあと、VWAP 方向へ戻り始めたタイミングで逆張りエントリー。",
        "concept": (
            "VWAP は「平均価格への回帰引力」があると考え、"
            "一方向に伸びすぎた価格が VWAP に向かって戻る動き（リクレイム）を狙います。"
            "モメンタム追随（vwap_ema）とは逆の、平均回帰アプローチです。"
        ),
        "entry_long": [
            "前足: 終値が VWAP より −0.5% 以上下にストレッチ",
            "当足: VWAP 方向へ −0.3% 以内まで戻った（部分リクレイム）→ ロング",
        ],
        "signal_buy": "VWAP より下に伸びすぎ（ストレッチ）→ 戻り始めで **買い**",
        "signal_sell": "VWAP より上に伸びすぎ（ストレッチ）→ 戻り始めで **売り**",
        "entry_short": [
            "前足: VWAP より +0.5% 以上上にストレッチ",
            "当足: +0.3% 以内まで戻った → ショート",
        ],
        "exit": [
            "利確: ATR × 2.0 / 損切: ATR × 1.0",
            "最大保有: 12 本、15:55 強制決済",
        ],
        "params": {
            "stretch_pct": "0.5% — VWAP からの乖離幅（ストレッチ判定）",
            "reclaim_pct": "0.3% — リクレイム完了とみなす戻り幅",
        },
        "market": "VWAP 付近を中心に往復する日、または一時的なオーバーシュート後。",
        "pros": ["トレンド追随と異なるロジックで分散", "VWAP 回帰はデイトレでよく使われる"],
        "cons": ["強いトレンド日は逆張りで連続損切り", "ストレッチ/リクレイム幅の調整が重要"],
        "tips": "vwap_ema と同時にバックテストし、相場環境によってどちらが効くか比較してください。",
    },
    "orb": {
        "title": "ORB（Opening Range Breakout）",
        "style": "デイトレ（5分足）",
        "styles": ["daytrade"],
        "summary": "寄り付き後の最初 20 分（Opening Range）の高値・安値をブレイクした方向にエントリー。",
        "concept": (
            "Opening Range Breakout は、米国株デイトレの古典手法。"
            "寄り付き直後のレンジ（最初の数本の 5 分足）を「その日の初期均衡」とみなし、"
            "レンジを抜けた方向に momentum が続くと仮定します。"
        ),
        "entry_long": [
            "当日の OR 高値（最初 20 分の最高値）を終値が上抜け",
            "出来高 > 20 本平均の 1.2 倍",
        ],
        "signal_buy": "寄り付きレンジ（OR）の **高値ブレイク** → 買い",
        "signal_sell": "寄り付きレンジ（OR）の **安値ブレイク** → 売り",
        "entry_short": [
            "OR 安値を終値が下抜け + 出来高確認",
        ],
        "exit": [
            "利確: ATR × 2.0 / 損切: ATR × 1.0",
            "最大保有: 12 本、15:55 強制決済",
            "1 日最大 3 トレード（設定）",
        ],
        "params": {
            "or_minutes": "20 — Opening Range の長さ（分）",
            "volume multiplier": "1.2 倍",
        },
        "market": "寄り付き後に方向感が出る日（決算・マクロイベント日など）。",
        "pros": ["ルールがシンプル", "寄り付きの流れをそのまま利用", "1 日 1 方向に集中しやすい"],
        "cons": ["レンジ day では両方向にダマシ", "寄り付き直後はスプレッド・スリッページが大きい"],
        "tips": "コストタブで Alpaca 保守モデルを見て、寄り付きのスリッページ耐性を確認してください。",
    },
}

STYLE_STRATEGY_MAP: dict[str, list[str]] = {
    "swing": ["macd_cross", "ema_pullback", "bb_squeeze"],
    "swing_high_winrate": ["macd_cross"],
    "daytrade": ["vwap_ema", "vwap_reclaim", "orb"],
}

STRATEGY_LABELS: dict[str, str] = {k: v["title"] for k, v in STRATEGY_GUIDES.items()}

_STYLE_LABELS = {
    "swing": "スイング（日足）",
    "swing_high_winrate": "スイング・高勝率",
    "swing_champion": "Champion プリセット",
    "daytrade": "デイトレ（5分足）",
}


def _catalog_entries() -> list[dict[str, Any]]:
    rows = [s for s in load_web_catalog().get("strategies", []) if s.get("implemented")]
    return sorted(rows, key=lambda s: (str(s.get("style") or ""), str(s.get("name") or s.get("id") or "")))


def _catalog_by_id() -> dict[str, dict[str, Any]]:
    return {str(s["id"]): s for s in _catalog_entries() if s.get("id")}


def _render_full_strategy_guide(strategy_key: str, guide: StrategyGuide) -> None:
    kind = "図解付きガイド" if strategy_key in STRATEGY_GUIDES else "テンプレート解説（自動）"
    st.markdown(f"### {guide['title']}")
    st.caption(f"**{guide['style']}**  |  キー: `{strategy_key}` · **{kind}**")
    st.info(guide["summary"])
    st.markdown("#### 考え方")
    st.write(guide["concept"])
    st.markdown("#### 📊 判断ポイント（図解）")
    st.caption(SIGNAL_LEGEND)
    sb1, sb2 = st.columns(2)
    with sb1:
        st.success(f"**🟢 買いシグナル:** {guide.get('signal_buy', '—')}")
    with sb2:
        sell = guide.get("signal_sell")
        if sell:
            st.error(f"**🔴 売りシグナル:** {sell}")
        else:
            st.warning("**🔴 売りシグナル:** なし（この戦略は買い専用）")
    default_chart = strategy_key in STRATEGY_GUIDES
    if st.checkbox("図解チャートを表示（Plotly）", value=default_chart, key=f"show_chart_{strategy_key}"):
        fig = plot_strategy_demo(strategy_key)
        if fig is not None:
            render_check_legend(strategy_key)
            st.plotly_chart(fig, width="stretch", key=f"strategy_visual_{strategy_key}")
        else:
            st.info("この戦略の図解は準備中です。")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🟢 買いシグナル — 詳細条件**")
        for rule in guide["entry_long"]:
            st.markdown(f"- {rule}")
    with c2:
        st.markdown("**🔴 売りシグナル — 詳細条件**")
        if guide.get("signal_sell") and guide.get("entry_short") and guide["entry_short"] != ["なし（ロング専用）"]:
            for rule in guide["entry_short"]:
                st.markdown(f"- {rule}")
        else:
            st.caption("売りシグナルは発生しません。")
    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**🚪 エグジット（決済）**")
        for rule in guide["exit"]:
            st.markdown(f"- {rule}")
    with c4:
        st.markdown("**📌 シグナルとポジション**")
        st.caption("買い → ロング / 売り → ショート。BT の ▲▼ と対応。")
    with st.expander("⚙️ 主なパラメータ", expanded=False):
        for name, desc in guide["params"].items():
            st.markdown(f"- **{name}**: {desc}")
    c5, c6, c7 = st.columns(3)
    with c5:
        st.markdown("**🎯 向いている相場**")
        st.caption(guide["market"])
    with c6:
        st.markdown("**✅ 長所**")
        for p in guide["pros"]:
            st.markdown(f"- {p}")
    with c7:
        st.markdown("**⚠️ 短所**")
        for c in guide["cons"]:
            st.markdown(f"- {c}")
    sources = guide.get("sources") or []
    if sources:
        with st.expander(f"参考ソース（{len(sources)} 件）", expanded=False):
            for src in sources[:25]:
                title = src.get("title") or src.get("url") or "—"
                url = src.get("url")
                if url:
                    st.markdown(f"- [{title}]({url})")
                else:
                    st.markdown(f"- {title}")

    st.markdown("---")
    st.markdown("**💡 このダッシュボードでの使い方**")
    st.caption(guide["tips"])
    st.caption("東証全銘柄 BT 成績: **📊 戦略結果 → TSE 実験** またはサイドバーから戦略を選択。")


@st.fragment
def render_strategies_tab() -> None:
    import pandas as pd

    catalog = _catalog_entries()
    n_deep = len(STRATEGY_GUIDES)
    n_all = len(catalog)
    st.subheader("📚 戦略解説")
    st.markdown(
        f"カタログ **{n_all} 戦略**すべてに、**エントリー条件・エグジット・パラメータ**を表示します。"
        f"（**{n_deep} 件**は図解付きの手書きガイド、残りは実装テンプレートから自動生成）"
    )

    styles = sorted({str(s.get("style") or "") for s in catalog})
    col1, col2 = st.columns([1, 2])
    with col1:
        style_filter = st.selectbox(
            "スタイルで絞り込み",
            ["すべて"] + styles,
            format_func=lambda x: "すべて" if x == "すべて" else _STYLE_LABELS.get(x, x),
            key="strategy_guide_style",
        )
        q = st.text_input("名前 / ID で検索", key="strategy_guide_search", placeholder="例: macd, vwap")
        pool = catalog
        if style_filter != "すべて":
            pool = [s for s in pool if s.get("style") == style_filter]
        if q.strip():
            needle = q.strip().lower()
            pool = [
                s
                for s in pool
                if needle in str(s.get("id", "")).lower() or needle in str(s.get("name", "")).lower()
            ]
        if not pool:
            st.warning("該当する戦略がありません。")
            return
        strategy_key = st.selectbox(
            "戦略を選択",
            [str(s["id"]) for s in pool],
            format_func=lambda k: f"{_catalog_by_id().get(k, {}).get('name', k)} ({k})",
            key="strategy_guide_pick",
        )
        if strategy_key in STRATEGY_GUIDES:
            st.success("図解付きガイド")
        else:
            st.caption("テンプレート解説（自動）")

    with col2:
        guide = resolve_strategy_guide(strategy_key)
        _render_full_strategy_guide(strategy_key, guide)

    with st.expander("カタログ全戦略一覧", expanded=False):
        df = pd.DataFrame(
            [
                {
                    "キー": s.get("id"),
                    "名前": s.get("name"),
                    "スタイル": _STYLE_LABELS.get(str(s.get("style")), s.get("style")),
                    "図解": "✓" if s.get("id") in STRATEGY_GUIDES else "自動",
                    "タグ": ", ".join(s.get("tags") or []),
                }
                for s in catalog
            ]
        )
        st.dataframe(df, width="stretch", hide_index=True, key="df_strategy_catalog")


def render_strategy_guide_summary(strategy_id: str) -> None:
    """Compact guide block for strategy detail side panels."""
    guide = resolve_strategy_guide(strategy_id)
    st.info(guide.get("summary") or "—")
    st.markdown("**考え方**")
    st.caption(guide.get("concept") or "—")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**買い**")
        for rule in (guide.get("entry_long") or [])[:6]:
            st.markdown(f"- {rule}")
    with c2:
        st.markdown("**エグジット**")
        for rule in (guide.get("exit") or [])[:5]:
            st.markdown(f"- {rule}")
    st.caption("全文は **📚 戦略解説** タブで確認できます。")
