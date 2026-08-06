"""Detailed strategy guide for the Streamlit dashboard (Japanese)."""

from __future__ import annotations

from typing import Any

import streamlit as st

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
        "market": "明確な上昇トレンドが続く相場（NVDA の AI ブーム期など）。レンジ相場ではダマシが増えます。",
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
        "pros": ["理屈がわかりやすい", "勝率が比較的安定しやすい", "NVDA のスイング向き"],
        "cons": ["強いトレンドでは押し目が浅くエントリー機会が少ない", "レンジ相場では EMA 付近で往復しやすい"],
        "tips": "ML フィルタと組み合わせると、押し目シグナルの質をさらに絞り込めます。",
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


def render_strategies_tab() -> None:
    st.subheader("📚 戦略解説")
    st.markdown(
        "SignalForge に実装されている **6 つの売買戦略** を、エントリー条件・イジット・向いている相場まで"
        "詳しく解説します。サイドバーで選ぶ戦略名と対応しています。"
    )

    col1, col2 = st.columns([1, 2])
    with col1:
        style_filter = st.selectbox(
            "スタイルで絞り込み",
            ["すべて", "swing", "swing_high_winrate", "daytrade"],
            format_func=lambda x: {
                "すべて": "すべて",
                "swing": "スイング（日足）",
                "swing_high_winrate": "スイング・高勝率",
                "daytrade": "デイトレ（5分足）",
            }.get(x, x),
            key="strategy_guide_style",
        )
        if style_filter == "すべて":
            options = list(STRATEGY_GUIDES.keys())
        else:
            options = STYLE_STRATEGY_MAP.get(style_filter, [])

        strategy_key = st.radio(
            "戦略を選択",
            options,
            format_func=lambda k: STRATEGY_LABELS.get(k, k),
            key="strategy_guide_pick",
        )

    guide = STRATEGY_GUIDES[strategy_key]
    with col2:
        st.markdown(f"### {guide['title']}")
        st.caption(f"**{guide['style']}**  |  キー: `{strategy_key}`")
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
        st.markdown("**🚪 イグジット（決済）**")
        for rule in guide["exit"]:
            st.markdown(f"- {rule}")
    with c4:
        st.markdown("**📌 シグナルとポジションの関係**")
        st.caption(
            "買いシグナル → ロング（株を買って値上がりで儲ける）\n\n"
            "売りシグナル → ショート（空売りして値下がりで儲ける）\n\n"
            "バックテストの「▲」「▼」マーカーと対応しています。"
        )

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

    st.markdown("---")
    st.markdown(f"**💡 このダッシュボードでの使い方**")
    st.caption(guide["tips"])

    st.markdown("---")
    st.markdown("#### スタイル別 対応表")
    rows = []
    for style, keys in STYLE_STRATEGY_MAP.items():
        label = {
            "swing": "スイング",
            "swing_high_winrate": "スイング・高勝率",
            "daytrade": "デイトレ",
        }.get(style, style)
        for k in keys:
            rows.append({"スタイル": label, "戦略": STRATEGY_LABELS[k], "キー": k})
    st.dataframe(rows, width="stretch", hide_index=True, key="df_strategy_map")
