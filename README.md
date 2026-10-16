# SignalForge

**日本株**（yfinance `*.T`）向けテクニカル分析 — **戦略は事前バックテスト済み**、ダッシュボードでは結果を **見るだけ**。

## 日常の使い方（3 ステップ）

```bash
uv sync --extra dev

# 0. 東証全銘柄リスト（JPX 公式・初回）
uv run signalforge universe refresh   # → data/universe/tse_listing.json（約 3,500 銘柄）

# 1. データ（初回 or 更新時・全銘柄は時間がかかります）
uv run signalforge fetch --universe tse_domestic --timeframe 1d
# 動作確認だけ: fetch --universe japan_liquid

# 2. 多軸実験（全銘柄 + 市場区分 + 33業種）→ docs/experiments.md
uv run signalforge experiments run

# 従来ハブ一括
uv run signalforge results build
uv run signalforge results build --quick

# 3. 結果を見る
uv run signalforge dashboard start        # Streamlit · ランキング閲覧
uv run signalforge hub open               # 静的グラフ HTML
uv run signalforge results status         # ファイル更新日時
```

## ダッシュボード

- **📊 戦略結果** — `catalog_backtests.json` / コホート / ラボの事前計算結果
- **📚 戦略解説** / **📖 用語集**
- **⚙️ 上級者** — 銘柄・期間を変えて再 BT（通常は不要）

```bash
uv run signalforge dashboard status
uv run signalforge dashboard stop
```

公開サイト（Paper 等）: https://tsugumasa320.github.io/signalforge/

## その他 CLI

```bash
uv run signalforge backtest --style swing --strategy macd_cross   # 単一 BT + ジャーナル
uv run signalforge cohort run --strategies catalog:swing --cohorts prime
uv run signalforge lab matrix --rules all --cohorts prime,standard,growth
uv run signalforge paper diversified-run-all                      # TSE 分散フォワード（1口座）
uv run signalforge doctor
uv run pytest
```

カタログ収集（メンテナンス用）: `strategies stats`, `strategies harvest`, `strategies collect-max`

## 設計

- 評価コスト既定: **日本株（japan）**
- ML フィルタは Walk-forward OOS
- OHLCV キャッシュ: `data/*.pkl`（gitignore）

詳細: [AGENTS.md](AGENTS.md), [docs/izanami_parity.md](docs/izanami_parity.md)
