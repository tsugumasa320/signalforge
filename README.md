# SignalForge

NVDA 向けマルチホライズン（スイング + デイトレ）テクニカル分析基盤。

## リンク

| 用途 | URL / コマンド |
|------|----------------|
| リポジトリ | https://github.com/tsugumasa320/signalforge |
| **ダッシュボード（公開）** | **https://tsugumasa320.github.io/signalforge/** |
| 自動更新ログ（Actions） | https://github.com/tsugumasa320/signalforge/actions/workflows/daily-paper.yml |
| Paper 成績（JSON） | https://github.com/tsugumasa320/signalforge/tree/main/data/paper |
| ダッシュボード（ローカル・Streamlit） | `uv run signalforge dashboard status` |

公開サイト: **Paper 全7口座 · バックテスト比較 · 6戦略解説** を統合（ローカル Streamlit 版と同等の戦略検討）。

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
# データ取得
uv run signalforge fetch --ticker NVDA --timeframe 1d

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

# Champion（最強プリセット — NVDA swing MACD + ML）
uv run signalforge champion
uv run signalforge backtest --style swing_champion --ml-filter
uv run signalforge paper run-all
uv run signalforge dashboard export   # 統合サイト → _site/

GitHub Actions で**毎日自動実行**（`.github/workflows/daily-paper.yml`）:
- 全7戦略の fetch + paper run + 統合ダッシュボード公開
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
