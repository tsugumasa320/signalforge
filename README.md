# SignalForge

**日本株**（yfinance `*.T`）向けマルチホライズン（スイング + デイトレ）テクニカル分析基盤。

## リンク

| 用途 | URL / コマンド |
|------|----------------|
| リポジトリ | https://github.com/tsugumasa320/signalforge |
| **ダッシュボード（公開）** | **https://tsugumasa320.github.io/signalforge/** |
| 自動更新ログ（Actions） | https://github.com/tsugumasa320/signalforge/actions/workflows/daily-paper.yml |
| Paper 成績（JSON） | https://github.com/tsugumasa320/signalforge/tree/main/data/paper |
| ダッシュボード（ローカル・Streamlit） | `uv run signalforge dashboard status` |

公開サイト: **Paper 複数口座 · バックテスト比較 · 戦略解説** を統合（ローカル Streamlit 版と同等の戦略検討）。

- **Primary Model**: 人間可読 YAML ルール（EMA Pullback, VWAP+EMA 等）
- **Secondary Model**: Meta-Labeling ML フィルタ（LightGBM + SHAP）
- **解釈性**: 全トレードにルール監査ログ + 日本語サマリー

## セットアップ

```bash
uv sync
cp .env.example .env
```

## 使い方

```bash
# データ取得（単一銘柄 / ユニバース一括）
uv run signalforge fetch --ticker 7203.T --timeframe 1d --with-correlations
uv run signalforge fetch --universe japan_liquid --timeframe 1d --refresh

# ユニバース横断スキャン
uv run signalforge scan --style swing --strategy macd_cross --limit 5

# Web 由来の戦略カタログ（全媒体台帳 media_sources.yaml + 手動 curation）
uv run signalforge strategies media       # 登録メディア一覧
uv run signalforge strategies collect-max   # harvest + カタログ拡張 + 実装マップ生成
uv run signalforge strategies backtest-all  # 全カタログ戦略を一括バックテスト（7203.T 等）

# 全戦略・全コホート一括検証 → ランキング/グラフ HTML ハブ
uv run signalforge hub build          # 実行に時間がかかります
uv run signalforge hub open           # ブラウザで data/reports/hub/index.html

# イザナミ風ラボ（ルール検証 → 結果概要 → 最終日シグナル / 分散近似）
uv run signalforge lab palette
uv run signalforge lab backtest --rule iz_macd_buy --cohort prime
uv run signalforge lab matrix --rules all --cohorts prime,standard,growth --ticker-limit 15
uv run signalforge lab signals --rule iz_macd_buy --cohort prime --allocate
uv run signalforge lab backtest --rule iz_dsl_volume_break --cohort prime --save-cache
uv run signalforge lab export-csv --input data/reports/lab_iz_macd_buy.json
# ダッシュボード「🔬 イザナミラボ」タブでも同ワークフロー

# 戦略 × プライム/スタンダード/グロース・業種コホート比較
uv run signalforge cohort presets
uv run signalforge cohort run --strategies macd_cross,rsi_reversal --cohorts prime,standard,growth
uv run signalforge cohort run --strategies catalog:swing --cohorts prime,sector_transport --strategy-limit 15
uv run signalforge cohort run --by segment --strategies macd_cross --ticker-limit 20
uv run signalforge strategies harvest
uv run signalforge strategies stats
uv run signalforge strategies catalog --tag kabutan

# スイングバックテスト
uv run signalforge backtest --style swing --strategy ema_pullback

# デイトレバックテスト
uv run signalforge backtest --style daytrade --strategy vwap_ema

# トレード説明
uv run signalforge explain --trade-id 1

# レポート
uv run signalforge report --format md

# 戦略比較
uv run signalforge compare --style swing --strategies ema_pullback,macd_cross

# ML フィルタ付き（Walk-forward OOS — 過学習防止）
uv run signalforge backtest --style swing --ml-filter

# TA vs ML 比較（OOS メトリクス付き）
uv run signalforge compare --style swing --strategies ema_pullback,macd_cross --ml-filter

# ダッシュボード（ターミナルを閉じても動き続ける）
uv run signalforge dashboard start
uv run signalforge dashboard status
uv run signalforge dashboard stop

# Champion（プリセット — 日本株 swing MACD + ML）
uv run signalforge champion
uv run signalforge backtest --style swing_champion --ml-filter
uv run signalforge paper run-all
uv run signalforge dashboard export   # 統合サイト → _site/

GitHub Actions で**毎日自動実行**（`.github/workflows/daily-paper.yml`）:
- 日本株ユニバース fetch + paper run-all + 統合ダッシュボード公開
- 手動実行は不要（デバッグ時のみ Actions タブから Run workflow 可）
- Alpaca 利用時は Secrets に `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` を設定
```

## テスト

```bash
uv run pytest
```

## 設計上の注意

- **ML フィルタ**は Walk-forward OOS のみ適用（学習期間と BT 期間を分離）
- CLI の `OOS 期間のみ` メトリクスが ML 評価の信頼指標
- **LightGBM** は macOS で `libomp` 未導入時 GradientBoosting にフォールバック
- 5 分足は yfinance だと約 60 日分。長期デイトレ BT には `.env` に Alpaca API キーを設定
