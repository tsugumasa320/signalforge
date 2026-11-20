# 決算サプライズ比較（C0–C3）

日本株の決算を使った短期の比較です。配点と閾値は `src/signalforge/research/earnings_surprise/config.py` に固定してあり、バックテスト結果を見て動かしていません。優位性が出るまでは確立した手法として扱いません。

## いまのキーで分かっていること

2026-11-11 にこの環境の `JQUANTS_API_KEY` で確認した範囲です。

| 項目 | 結果 |
| --- | --- |
| 株価・売買代金 | `/equities/bars/daily`。無料プランは約2年で、末日は動く。2026-11-11 時点では 2024-08-20 〜 2026-08-20。5年分ではない |
| 決算 | `/fins/summary` の `DiscDate` と `DiscTime`。売上、営業利益、EPS、会社の通期予想 |
| 市場コンセンサス | 応答に無い。会社予想の上方修正や前年同期比と混ぜない |
| 決算カレンダー | `code` を付けてもその銘柄の過去発表は返らない |
| 公式 TOPIX・日経・業種指数 | 403。ベンチマークは 1306（コード `13060`）の調整後株価 |
| 分足 | 403。翌営業日 VWAP（方法B）は未実施 |
| ストップ高安 | `UL` / `LL` はほぼ 0。判定に使わない |

場中発表の相対強度は、発表日の終値を使いません。公開前の最後の引けまでです。日足しかないので、約定は翌営業日の寄り付き（9時前の発表だけ当日寄り）です。

## 戦略

- **C0** 会社の通期営業利益予想が上方修正、または前年同期比で営業利益が増え営業利益率も改善
- **C1** C0 かつ セクター20日 − ベンチマーク20日 > 0
- **C2** C0 かつ 個別−ベンチマーク20日 > 0 かつ 個別−セクター20日 > 0
- **C3** C2 かつ セクター相対強度20日 > 0。市場が弱いだけでは除外しない

100点スコアは欠測を0点にします。エントリーには使いません。業績持続性20点は短信サマリーにありません。

## 実行

```bash
cd /Users/tsugumasayutani/Documents/GitHub/signalforge
uv run python -m signalforge.research.earnings_surprise probe
uv run python -m signalforge.research.earnings_surprise inspect --code 72030
uv run python -m signalforge.research.earnings_surprise fetch-sample --n 100
uv run python -m signalforge.research.earnings_surprise run
```

`fetch-sample` はプラン初日の売買代金が大きいプライム普通株を、その日の出来高で100銘柄選びます。キャッシュがあれば再開します。セクター相対強度はこの100銘柄の中だけで計算するので、プライム全体の業種指数ではありません。

出力は `data/earnings_surprise/output/` です。

- `report.md` … 条件、欠損、10の問い
- `earnings_surprise.xlsx` … 全取引、C0〜C3、年別、業種、市場環境、未約定、データ品質
- `trades.csv` … 保有5/10/20日と損切り -3/-5/-8% を含む
- `equity.csv` / `equity.html` … 1,000万円口座の評価額とドローダウン

APIキーは `.env` の `JQUANTS_API_KEY` です。ソースには書きません。
