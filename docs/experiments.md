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
uv run signalforge experiments watch        # tqdm 風に同一画面で更新（ETA 付き）

./scripts/run-experiments-daemon.sh          # BT 起動 + このターミナルで watch
WATCH_INTERVAL=3 ./scripts/run-experiments-daemon.sh

./scripts/start-experiments-supervisor.sh    # BT が落ちたら自動再開（推奨・長時間）
./scripts/stop-experiments-supervisor.sh
uv run signalforge experiments supervisor-status

uv run signalforge experiments aggregate  # JSON のみから矩阵再生成
uv run signalforge experiments compact    # 既存 JSON を slim 化 + 銘柄 sidecar 分離
```

### 静的サイト（CI 向け）

```bash
uv run signalforge dashboard export --guides-only --output _site
```

### 夜間自動再開（macOS launchd）

```bash
chmod +x scripts/install-experiments-launchd.sh
./scripts/install-experiments-launchd.sh
# 手動: launchctl start com.signalforge.experiments
```

Mac がスリープすると BT は止まります。

**蓋を閉じる（バッテリーのまま）:** `caffeinate` だけでは足りないことが多いです。次を使うと **バッテリー pmset でスリープを抑止**します（初回 `sudo` パスワード・発熱・消費増・**閉じた本体をバッグに入れない**）。

```bash
./scripts/rerun-experiments-series-closed-lid.sh
# 完了後: ./scripts/restore-battery-sleep.sh
```

**電源接続時:** `./scripts/rerun-experiments-series.sh`（`caffeinate -dims -u -s`）で十分なことが多いです。

### 途中で止まるとき（Cursor / ターミナルを閉じた等）

ログに Traceback が **ない** のに `experiments run` だけ消える場合、**親シェルや IDE から SIGTERM が送られた**ことが多いです（`nohup` だけでは不十分な環境あり）。**Cursor 上の Agent が起動したバックグラウンド job もセッション終了で止まり得ます**。

**推奨:**

```bash
./scripts/run-experiments-daemon.sh   # PID → data/reports/experiments.pid, caffeinate -dims -s
./scripts/rerun-experiments-series.sh # 系列追記（上と同じ daemon・蓋閉じ向け）
# 落ちたら自動再開: ./scripts/start-experiments-supervisor.sh（内部も caffeinate -dims）
# または macOS 夜間: ./scripts/install-experiments-launchd.sh
```

`experiments run | head` のように **パイプで途中切断** すると `Broken pipe` で戦略 JSON が壊れるので禁止。

## 指標の読み方（日本語）

| 表示名 | 意味 |
|--------|------|
| **損益比（PF）** | 1 銘柄の BT で、利益合計 ÷ 損失合計。1.0 超でプラス方向。 |
| **中央値の損益比** | 全銘柄の損益比を並べた **真ん中**。TSE 実験の戦略比較の主指標（極端な1銘柄の影響を抑える）。 |
| **平均の損益比** | 銘柄損益比の平均。外れ値の影響を受けやすい。 |
| **損益比が1超の銘柄比率** | 損益比 > 1.0 の銘柄が何割か。 |

### 儲かるかどうか — 見る指標（早見表）

| 優先 | 指標 | 見る場所 | 儲かる目安 | 補足 |
|------|------|----------|------------|------|
| 1 | 総リターン（%） | 戦略詳細 · 銘柄別 · 単銘柄 BT | プラス | 期間トータルで資金が増えたか |
| 2 | 1トレード期待値（%） | ラボ「期待値%」· CLI Avg PnL | 0 より大 | 取引数が少ないと偶然に注意 |
| 3 | 損益比（PF） | TSE 一覧 · 各種表 | 1.05 以上目安 | 1 未満は期待値マイナス方向 |
| 4 | 取引数 | 各画面 | 十分な回数 | 目安 100 回以上で 1〜3 が信頼しやすい |
| 5 | Max DD | 単銘柄 BT · 資産曲線 | 許容できる下落 | 儲かっても途中のドローダウンで運用不可になり得る |

| やりたいこと | まず見る | 次に見る |
|--------------|----------|----------|
| 1銘柄で使う？ | 総リターン · PF · 取引数 | 資産曲線 · Max DD |
| TSE 全銘柄比較 | 中央値の損益比 | 詳細 → 銘柄別総リターン |
| ラボルール | 期待値% | PF · 勝率 |
| これから先 | ペーパートレード資産 | — |

ダッシュボード **📖 用語集** 冒頭にも同じ表があります。

### 資金制約（同時に使える金）

バックテストでは `config/backtest.yaml` の **capital** と `config/market/japan.yaml` の **backtest_capital_hint** で調整できます。

| キー | 意味 |
|------|------|
| `initial_cash_jpy` | 口座サイズ（円） |
| `max_position_pct` | 1エントリーで使える口座の上限（例 0.35 = 35%） |
| `min_cash_reserve_pct` | 常に残す現金（例 0.10 = 10%） |

**TSE 実験**は銘柄ごとに上記ルールで **独立口座** として BT します。  
**1口座・分散制約**（実運用に近い近似）: 口座 ¥300万 · 同時最大 5 銘柄 · 1 回 20% · 先着（枠が埋まればスキップ）。

```bash
uv run signalforge experiments portfolio macd_cross
uv run signalforge paper diversified-init --strategy macd_cross --cohort prime --workers 8
uv run signalforge paper diversified-run-all --refresh --workers 8
./scripts/run-diversified-paper-prime.sh   # 分散フォワード5戦略 · プライム（ログ: data/logs/diversified-paper-prime.log）
```

分散フォワード既定10戦略（`DIVERSIFIED_PAPER_SIMULATIONS`）: 上記5 + `low_pbr_value_reversal`, `ichimoku_tk_cross`, `gap_fill_reversal`, `macd_cross`, `ema_pullback`

実験だけ別口座にしたい場合は `config/experiments/backtest_plan.yaml` の `meta.backtest_capital`、または run 時の CLI / 環境変数を使います。

```bash
uv run signalforge experiments capital   # 有効な条件と「古い」完了戦略数
uv run signalforge experiments run --ignore-schedule --workers 8 \
  --initial-cash-jpy 5000000 --max-position-pct 0.25 --refresh-capital
# 環境変数: INITIAL_CASH_JPY, MAX_POSITION_PCT, MIN_CASH_RESERVE_PCT
# スクリプト: INITIAL_CASH_JPY=5000000 ./scripts/rerun-experiments-capital.sh
```

完了戦略 JSON には `backtest_capital` が記録されます。設定を変えたら `--refresh-capital` で再BTしないと表の数値は古い条件のままです。

### 指標更新の再BT（期待値・最大DD）

旧 sidecar には `avg_pnl_pct` / `max_drawdown_pct` が無いことがあります。

```bash
chmod +x scripts/rerun-experiments-metrics.sh
./scripts/rerun-experiments-metrics.sh
# 同等: REFRESH_METRICS=1 ./scripts/run-experiments-daemon.sh
# CLI: uv run signalforge experiments run --ignore-schedule --workers 8 --refresh-metrics
```

`--refresh-metrics` は **期待値・最大DD が無い銘柄だけ** 再BTします（済み銘柄は sidecar を再利用）。未完了戦略も resume 時に同様。資金変更は `--refresh-capital` で戦略丸ごと再BT。

## 出力

| ファイル | 内容 |
|---------|------|
| `data/reports/experiments/strategies/<id>.json` | 集計メタ（universe / segment / sector） |
| `strategies/<id>.tickers.json` | 銘柄別行（本体 JSON から分離・ダッシュボードは必要時のみ読込） |
| `matrix_segment.json` | 戦略 × 市場区分 |
| `matrix_sector.json` | 戦略 × 33業種 |
| `summary.json` | 全銘柄ランキング |
| `catalog_backtests.json` | ダッシュボード用（自動同期） |

## 一括実行の軽量化（情報量は維持）

`experiments run` / コホート比較は **bulk モード**（既定）です。

| やめること | 残すこと |
|------------|----------|
| 銘柄ごとの `data/reports/journal_*.json`（47 万ファイル級） | 各銘柄の **PF / Win率 / trades 等トップレベル指標**（nested metrics 三重は compact で削除） |
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
- `checkpoint_every: 50` → checkpoint JSON の書き込み間隔（I/O 軽減）

## 実行順序

`catalog:all` では **ML 重いスタイル（swing_champion / swing_high_winrate）を後回し** に並べます（`experiments/order.py`）。通常スイング・デイトレを先に完了させます。

## 所要時間の目安

133 戦略 × 3,520 銘柄 ≒ 47 万回 BT。キャッシュ済みでも **数十時間** 規模。  
並列ワーカーと resume で **実時間は短縮**、計算対象件数は減らさない。
