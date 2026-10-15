# J-Quants の使い方（SignalForge）

信用残ベースの戦略（`credit_balance_contrarian` など）用です。

## 1. 登録

1. [J-Quants API](https://jpx-jquants.com/) でユーザー登録（**Free プラン**可）
2. ダッシュボード **Settings → API Key** でキーを発行

## 2. キーを環境に設定

```bash
export JQUANTS_API_KEY='あなたのAPIキー'
```

またはリポジトリ直下の `.env`（gitignore 済み）:

```
JQUANTS_API_KEY=あなたのAPIキー
```

## 3. 接続確認

```bash
cd /Users/tsugumasayutani/Documents/GitHub/signalforge
uv run signalforge alt-data jquants-test
```

## 4. 決算日（Free プランで可）

`JQUANTS_API_KEY` があるとき `--earnings` は **J-Quants 決算カレンダー** を使います。

```bash
uv run signalforge alt-data fetch --earnings --limit 50
uv run signalforge alt-data fetch --earnings   # 全銘柄（時間がかかります）
```

## 5. 信用残（有料プラン）

`/v2/markets/margin-interest` は **Free では 403** になることがあります。  
その場合 `credit_balance_contrarian` の本データ BT にはプランアップが必要です。

```bash
uv run signalforge alt-data fetch --jquants-credit --limit 20
```

保存先: `data/alt/credit_margin/{ticker}.json`

## 6. 再バックテスト

```bash
uv run signalforge alt-data invalidate-experiments
uv run signalforge experiments run --ignore-schedule --workers 8
```

詳細: [alt_data.md](./alt_data.md)
