# 長期上昇トレンド・シストレ（採用版）

現行採用は改善レース後の版 1.2（`data/trend_screen/system/adopted.json`）。

## コマンド

```bash
uv run signalforge trend-screen rules
uv run signalforge trend-screen targets
uv run signalforge trend-screen ranking   # 全通過銘柄ランキング → data/published/trend_screen_ranking.json
uv run signalforge trend-screen forward   # 2023〜フォワード仮想口座 → data/paper/trend_screen.json
uv run signalforge trend-screen backtest
uv run signalforge trend-screen improve
uv run signalforge dashboard export --output _site   # Pages に screen/trend.html
```

GitHub Pages: `/screen/trend.html`（ナビ「トレンド・スクリーニング」）。  
ページ上の **条件ラボ**（安定度スコア・上昇月割合・経路DD、直近/次回決算、配当利回り・権利落、優待、Yahooファイナンス日本版リンクなども参考表示） で一次条件・売買代金・直近20日・25日線・52週DD・上位N・並び替えを切り替え、通過銘柄をその場で再ランキングできる（ブラウザ内のみ。採用ルールは変わらない）。  
企業イベントは通過条件に使わない。優待は [優待しらべ](https://yutai-shirabe.com/download/index.html)（EDINET 有報由来）、配当は yfinance、決算日は `data/alt/earnings` キャッシュ。  


**基準日:** サイトのランキングは「日足が揃う最新営業日」で毎日更新する。  
**月末シグナル:** 採用シストレの売買（リバランス）だけが完了月末で判定する（別表示）。

日次更新: `.github/workflows/daily-paper.yml`（JST 18:17）が流動性ユニバースの日足更新 → `ranking` + `forward` → `dashboard export`。

## 規則（1.2）

1. 流動性上位300の普通株
2. 日足の一次条件6つ
3. 20日売買代金が5,000万円以上
4. 過去20営業日の株価リターンがプラス（直近下落なし）
5. 過去1年リターン上位5を等金額
6. 毎月末判定 → 翌営業日終値でリバランス

## 改善レースの結果

- 2026-11-13: 「上位5・売買代金下限」が学習最良（版1.1）
- 2026-11-14: 直近下落フィルタを追加比較。「上位5・直近20日下落なし」が学習CAGR最大かつ確認で1306超過プラス（版1.2）。確認CAGRはベースより抑えめだが、急落後の高騰銘柄を除外する。

詳細: `data/reports/trend_screen/improve/2026-11-13/improve.md`
