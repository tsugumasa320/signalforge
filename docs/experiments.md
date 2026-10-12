# 東証多軸バックテスト実験

## 設計

| 項目 | 内容 |
|------|------|
| 銘柄母集団 | JPX「東証上場銘柄一覧」内国株式（約 3,520） |
| 戦略 | カタログ実装済み全件（`catalog:all`） |
| 1回の計算 | 戦略 × 全銘柄を **1パス** のみ実行 |
| 事後集計 | 全銘柄 / プライム / スタンダード / グロース / 33業種 |

再計算の無駄を避けるため、市場区分・業種別は **同じ per-ticker 結果のグループ集計** です。

## コマンド

```bash
uv run signalforge universe refresh
uv run signalforge fetch --universe tse_domestic --timeframe 1d   # 初回は並行推奨

uv run signalforge experiments plan
uv run signalforge experiments run          # 全戦略・全銘柄（再開可能）
uv run signalforge experiments status
uv run signalforge experiments aggregate  # JSON のみから矩阵再生成
```

## 出力

| ファイル | 内容 |
|---------|------|
| `data/reports/experiments/strategies/<id>.json` | 銘柄別 + segment/sector 集計 |
| `matrix_segment.json` | 戦略 × 市場区分 |
| `matrix_sector.json` | 戦略 × 33業種 |
| `summary.json` | 全銘柄ランキング |
| `catalog_backtests.json` | ダッシュボード用（自動同期） |

## 一括実行の軽量化（情報量は維持）

`experiments run` / コホート比較は **bulk モード**（既定）です。

| やめること | 残すこと |
|------------|----------|
| 銘柄ごとの `data/reports/journal_*.json`（47 万ファイル級） | 各銘柄の **metrics / metrics_oos / metrics_in_sample** 一式 |
| メモリ上の trades・equity・df の保持 | `strategies/<id>.json` の銘柄別行 + segment/sector/universe 集計 |

ダッシュボードで **1 銘柄を詳細に再実行** するときは従来どおりジャーナル付き。一括結果の分析情報は **実験 JSON に集約** されます。

既存の `journal_*.json` は手動削除して問題ありません（実験 JSON を残す前提）。

コード反映後に `experiments run` を再起動すると、以降の銘柄から journal は増えません（checkpoint から再開可）。

## 省略しない／効率化の意味

| 動作 | 説明 |
|------|------|
| デフォルト | **全戦略 × 全 TSE 内国株式**（`strategy-limit` / `ticker-limit` / `max_tickers_per_strategy` がすべて **0** のとき） |
| サンプリング | なし。`run_cohort_backtests` はリストの銘柄を **1件ずつ** BT（並列は速度のみ） |
| skip 表示 | **その戦略ですでに全銘柄分の JSON が `complete: true` のときだけ**再計算を省略 |
| 途中停止 | `schedule.yaml` の `max_minutes_per_run` や時間帯で止めても、**checkpoint** と部分 JSON から **銘柄単位で再開** |
| 集計 | segment / sector は **同じ per-ticker 結果のグループ集計**（BT の二重実行ではない） |

試験だけ小さくしたいときは **明示** する: `--strategy-limit 5 --ticker-limit 50`

## スケジュール・並列

`config/experiments/schedule.yaml` と CLI:

```bash
uv run signalforge experiments schedule   # 現在の execution 設定を表示
uv run signalforge experiments run --ignore-schedule --workers 8
uv run signalforge experiments run --max-minutes 120   # 2時間で一旦停止（再 run で続き）
```

- `parallel_workers: 0` → CPU に応じて自動（最大 8）
- `sleep_seconds_per_*` → API 負荷調整用（0 ならスリープなし）

## 所要時間の目安

133 戦略 × 3,520 銘柄 ≒ 47 万回 BT。キャッシュ済みでも **数十時間** 規模。  
並列ワーカーと resume で **実時間は短縮**、計算対象件数は減らさない。
