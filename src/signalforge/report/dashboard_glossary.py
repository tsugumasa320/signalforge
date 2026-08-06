"""Dashboard glossary and inline help text (Japanese)."""

from __future__ import annotations

import streamlit as st

# --- Metric tooltips (st.metric help=) ---

METRIC_HELP: dict[str, str] = {
    "PF": "損益比（Profit Factor）。勝ちトレードの合計 ÷ 負けトレードの合計。1.0 超ならプラス、1.05 超ならコスト込みでも利益余地ありと判断。",
    "Win率": "勝ちトレード数 ÷ 全トレード数。高いほど当たりやすいが、1回の損失が大きいと総合的には負けることもある。",
    "Sharpe": "シャープレシオ。リターンのぶれ（リスク）あたりの効率。高いほど安定して儲かっている。目安: 1.0 以上で良好。",
    "Max DD": "最大ドローダウン。資産のピークからの最大下落率（%）。小さいほど資産が大きく減りにくい。",
    "取引数": "バックテスト期間中の売買回数。少なすぎると結果の信頼性が低い（偶然の可能性）。",
    "規制費用": "SEC・FINRA TAF・CAT など、米国の売買にかかる法定費用（Alpaca モデル）。",
    "スリッページ": "注文価格と実際の約定価格の差によるコスト。板の薄さや急変時に大きくなる。",
    "1取引あたりコスト": "（規制費用 + スリッページ）÷ 取引数。1回の売買で平均いくら失うか。",
    "Gross PF": "コストを引く前の損益比。手数料・スリッページを差し引く前の「素の」戦略性能。",
    "OOS PF": "Out-of-Sample（未学習期間）の損益比。ML フィルタ使用時、未来データに近い期間での成績。",
    "OOS Win率": "未学習期間（OOS）での勝率。過学習していないかの確認に使う。",
}

SIDEBAR_HELP: dict[str, str] = {
    "style": "取引の時間軸。スイング＝日足で数日〜数週間保有。デイトレ＝5分足で当日中に決済。",
    "strategy": "売買ルールの種類（MACD クロス、EMA 押し目など）。「全戦略を比較」で横並び評価できる。",
    "ml_filter": "機械学習で「勝ちやすいシグナルだけ通す」フィルタ。Walk-Forward で未来リークを防ぎ、OOS 期間で評価。",
    "cost_model": "バックテストに載せる取引コストの想定。Alpaca＝米国株ブローカーの公式料金表ベース。",
    "macd_opt": "macd_cross 用に最適化したパラメータ（ADX・EMA200・利確/損切幅など）を使う。",
    "backtest": "過去の株価データで戦略をシミュレーションし、儲かるか検証する。",
    "compare": "同じスタイル内の全戦略を一括バックテストし、PF などで比較する。",
    "verify_costs": "Legacy / Alpaca / 保守 の3パターンでコストを変え、利益が残るか確認する。",
}

STYLE_DESCRIPTIONS: dict[str, str] = {
    "swing": "日足チャート。数日前後〜数週間保有。NVDA の中長期トレンド向け。",
    "swing_high_winrate": "日足・高勝率向けに調整した MACD 設定。ML フィルタ推奨。評価期間は AI ブーム以降（2023〜）。",
    "daytrade": "5分足。当日中にエントリー・決済。Alpaca API データ使用時のみ。",
}

STRATEGY_DESCRIPTIONS: dict[str, str] = {
    "macd_cross": "MACD がシグナル線を上抜け（ゴールデンクロス）したら買い。トレンドフィルタ（EMA・ADX）付き。",
    "ema_pullback": "上昇トレンド中、価格が EMA に押し目を作ったら買い。",
    "bb_squeeze": "ボリンジャーバンドが収縮（スクイーズ）後のブレイクアウトを狙う。",
    "vwap_ema": "VWAP と EMA の位置関係でデイトレの方向を判断。",
    "vwap_reclaim": "価格が VWAP を下から取り戻したタイミングで買い。",
    "orb": "Opening Range Breakout。寄り付き後のレンジ突破でエントリー。",
}

GLOSSARY_SECTIONS: dict[str, list[tuple[str, str]]] = {
    "基本": [
        ("バックテスト", "過去の株価で戦略を仮想売買し、儲かったか検証すること。未来は保証されない。"),
        ("NVDA", "このダッシュボードの対象銘柄（エヌビディア）。設定で他銘柄にも拡張可能。"),
        ("評価期間", "分析に使うデータの開始〜終了日。古すぎる相場は現在と乖離するため 2023 年以降に限定している。"),
        ("Run ID", "1回のバックテスト実行ごとの識別子。ジャーナル（取引ログ）のファイル名に使われる。"),
    ],
    "パフォーマンス指標": [
        ("PF（損益比 / Profit Factor）", "総利益 ÷ 総損失。1.0 = トントン、1.05 超 = コスト込みでもプラス期待。"),
        ("Win率", "勝ち ÷ 全トレード。勝率が高くても、1回の大負けで PF が 1 未満になり得る。"),
        ("Sharpe（シャープレシオ）", "リターン ÷ リスク（ぶれ）。高いほど効率的。0 以下は現金保有より劣る可能性。"),
        ("Max DD（最大ドローダウン）", "資産最高値からの最大下落（%）。-20% ならピーク比で 2 割減った局面がある。"),
        ("総リターン", "期間全体の資産増減率（%）。PF と合わせて見る。"),
        ("Gross PF", "スリッページ・規制費を引く前の PF。Net PF との差 = コストの影響。"),
    ],
    "ML・検証": [
        ("ML フィルタ", "テクニカルシグナルのうち、機械学習が「勝率が高そう」と判断したものだけ実行。"),
        ("Meta-Labeling", "「買いシグナルが出たが、本当に入るべきか」を別モデルで判定する手法。"),
        ("Walk-Forward", "時系列順に「学習期間 → テスト期間」をずらしながら検証。未来のデータで学習する作弊を防ぐ。"),
        ("OOS（Out-of-Sample）", "モデルが学習していない期間のデータ。ここでの成績が実運用に近い。"),
        ("IS（In-Sample）", "学習に使った期間。IS だけ良く OOS が悪い = 過学習のサイン。"),
        ("SHAP", "ML の「なぜこの取引を採用/拒否したか」を各指標の寄与度で説明する手法。"),
        ("OOS accuracy", "各 Walk-Forward  fold で、ML が「勝ち/負け」を当てた割合の平均。"),
    ],
    "コスト・約定": [
        ("Alpaca", "米国株向けネオブローカー。株式手数料 $0（規制費は別途）。"),
        ("SEC 規制費", "売却代金に比例する米国 SEC 向け費用（売りのみ）。"),
        ("FINRA TAF", "売却株数に応じた FINRA 費用（売りのみ、1 回上限あり）。"),
        ("CAT", "取引報告用の FINRA 費用（買い・売り両方）。"),
        ("スリッページ", "理想価格と約定価格の差。バックテストでは bps（万分率）で仮定。"),
        ("Legacy コスト", "簡易モデル（古い検証用）。Alpaca 公式より楽観的になりがち。"),
        ("Alpaca 保守", "スリッページを広めに見積もった pessimistic シナリオ。"),
    ],
    "チャート・テクニカル": [
        ("MACD", "移動平均の差とそのシグナル線。ゴールデンクロス = 買いシグナルの例。"),
        ("EMA", "指数移動平均。直近の価格を重視したトレンド線。"),
        ("ADX", "トレンドの強さ（方向は別）。一定以上で「トレンド相場」とみなすフィルタに使用。"),
        ("ATR", "値動きの大きさ（ボラティリティ）。利確・損切の幅を「ATR の N 倍」で決める。"),
        ("VWAP", "出来高加重平均価格。デイトレの基準線として使う。"),
        ("PnL", "Profit and Loss。1 取引または累計の損益。"),
        ("bars", "足の本数。日足なら 5 bars ≒ 5 営業日保有。"),
        ("Long / Short", "Long = 買いから入って値上がりで儲ける。Short = 売りから入る（空売り）。"),
    ],
}


def render_sidebar_glossary_link() -> None:
    st.sidebar.markdown("---")
    with st.sidebar.expander("📖 用語集（全一覧）", expanded=False):
        for section, items in GLOSSARY_SECTIONS.items():
            st.markdown(f"**{section}**")
            for term, desc in items:
                st.markdown(f"- **{term}**: {desc}")


def render_glossary_tab() -> None:
    st.subheader("📖 用語集")
    st.markdown(
        "ダッシュボード内の略語・専門用語の意味をまとめています。"
        "サイドバーの各項目にも `?` マークで短い説明があります。"
    )
    for section, items in GLOSSARY_SECTIONS.items():
        with st.expander(f"**{section}**", expanded=(section == "基本")):
            for term, desc in items:
                st.markdown(f"**{term}**")
                st.caption(desc)

    st.markdown("---")
    st.markdown("#### 戦略一覧")
    for name, desc in STRATEGY_DESCRIPTIONS.items():
        st.markdown(f"- **{name}**: {desc}")


def render_tab_intro(title: str, body: str) -> None:
    with st.expander(f"ℹ️ {title}", expanded=False):
        st.markdown(body)


TAB_INTROS: dict[str, tuple[str, str]] = {
    "overview": (
        "このタブの見方",
        "上段の **判定バッジ** でコスト込みの総合評価を確認。**PF・Win率・Sharpe** は数字が大きいほど良い（Max DD は小さいほど良い）。"
        "ML フィルタ ON 時は **OOS** 行が実運用に近い成績。右のグラフは資産の増減と下落幅（ドローダウン）を表示。",
    ),
    "charts": (
        "チャートの見方",
        "上: 株価と売買ポイント（▲ 買い / ▼ 売り）。下左: 取引ごとの損益。下右: 損益の累積。"
        "緑系 = 勝ち、赤系 = 負け。",
    ),
    "compare": (
        "戦略比較の見方",
        "同じスタイル（日足 or 5分足）内の戦略を横並び。**PF** が最も重要。"
        "**scope** が OOS の行は ML フィルタ使用時の未学習期間の成績。",
    ),
    "costs": (
        "コスト分析の見方",
        "実際の Alpaca 取引を想定した費用内訳。**3モデル検証** で Legacy / 標準 / 保守 を比較し、"
        "どの前提でも PF≥1 か確認する。スリッページが総コストの大半になることが多い。",
    ),
    "trades": (
        "トレード詳細の見方",
        "各取引のエントリー・決済時刻、損益率、保有 bars、決済理由を表示。"
        "**OOS トレードのみ** に絞ると ML 検証期間だけ見られる。",
    ),
    "ml": (
        "ML / 監査の見方",
        "**SHAP** バー: 緑 = 採用理由、赤 = 却下要因。**拒否シグナル** は ML が「入らない」と判断した場面。"
        "ML フィルタ OFF ではこのタブはほぼ空。",
    ),
}
