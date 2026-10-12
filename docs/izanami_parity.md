# イザナミ機能対応表（SignalForge Lab）

参考: [イザナミ 検証画面](https://www.izanami.jp/v2support/bkt_summary.html)

| イザナミ | SignalForge | 状態 |
|---------|-------------|------|
| バックテスト（資金制約なし） | `lab backtest` / `event_backtest` + `execution` | ✅ |
| 結果概要（勝率・期待値・PF・分布） | `overview` in JSON / ダッシュボードタブ | ✅ |
| 約定率・未約定（指値/ストップ高安/出来高） | `fill_stats` / `unfilled` | ✅（簡易） |
| 最適分散投資 | `portfolio_sim` / ダッシュボード | ✅（近似） |
| 最終日シグナル | `lab signals` / ダッシュボード | ✅ |
| 仕掛けパレット | `izanami_palette.yaml` + DSL | ✅（拡張中） |
| 手仕舞いパレット | ATR TP/SL + max_hold | ✅（単一セット） |
| 対象銘柄（市場・業種） | `compare_presets` + `japan_equity_meta` | ✅ |
| 検証期間一括 | `--start` / `--end` | ✅ |
| 複数ルール比較 | `lab matrix` | ✅ |
| 日次シグナルグラフ | `daily_signal_bars` / Streamlit | ✅ |
| 期間別・業種別・銘柄別集計 | `overview.aggregations` | ✅ |
| 取引一覧 CSV | `lab export-csv` | ✅ |
| 差分検証キャッシュ | `data/lab_cache/` + `--save-cache` | ✅（近似） |
| GUI 4タブ | Streamlit「🔬 イザナミラボ」 | ✅ |
| ランキング/相場情報連携 | — | ❌ |
| .str ルールインポート | — | ❌ |
| パラメータ最適化 UI | `optimize` / champion（別系統） | △ |
| 場中・ティック | 日足/分足 fetch のみ | △ |
| 本家と同一の分散最適化 | 均等配分+同時保有上限 | △ |

## コマンド早見

```bash
uv run signalforge lab palette
uv run signalforge lab backtest --rule iz_macd_buy --cohort prime --save-cache
uv run signalforge lab matrix --rules all --cohorts prime,standard,growth
uv run signalforge lab export-csv --input data/reports/lab_iz_macd_buy.json
uv run signalforge dashboard start   # → イザナミラボ タブ
```
