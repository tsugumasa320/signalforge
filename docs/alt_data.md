# 代替データ（OHLCV 以外）と近似戦略

TSE 実験の多くは **日足 OHLCV のみ** で回せますが、カタログには「信用残」「みんかぶ人気」「ペアトレード」など **別データが要る** 戦略も含まれます。  
従来は `implementation_map.yaml` の **approximation（代理テンプレ）** で無理やり BT しており、**名前だけ違って結果が同じ** 行が並びます。

## いま実装済み

| データ | 保存先 | 取得コマンド | 使う戦略例 |
|--------|--------|--------------|------------|
| **業種 EW 指数** | `data/alt/sector_indices/` | `uv run signalforge alt-data fetch --sectors` | `sector_leader_laggard`, `bnf_sector_leading_swing`, `pairs_trading_sector` |
| **決算日（yfinance）** | `data/alt/earnings/*.json` | `uv run signalforge alt-data fetch --earnings` | `earnings_drift`, `kabutan_theme_swing_earnings` |
| **信用残（J-Quants V2）** | `data/alt/credit_margin/*.json` | `uv run signalforge alt-data fetch --jquants-credit` | `credit_balance_contrarian` |

BT 時に `pipeline` が `alt_data.enrich` で列を付与し、専用テンプレ（`sector_relative_momentum` 等）がシグナルを出します。

```bash
uv run signalforge alt-data status
uv run signalforge alt-data fetch --all          # 初回（earnings は全銘柄で数時間）
uv run signalforge alt-data invalidate-experiments # 旧 JSON 削除
uv run signalforge experiments run --ignore-schedule --workers 8
```

**前提:** 業種指数は既存 OHLCV キャッシュから構築します。未 fetch の銘柄が多い場合は先に:

```bash
uv run signalforge fetch --universe tse_domestic --timeframe 1d
```

## まだ代理のまま（要別ソース）

| 種別 | 例 | 理由 |
|------|-----|------|
| 信用・貸借 | （上表） | [jquants_setup.md](./jquants_setup.md) |
| 掲示板 / SNS | `minkabu_community_sentiment_rank`, `x_*` | 公式 API なし |
| 板・VWAP  intraday | デイトレ系の多く | 5 分足・板データ（yfinance は短期のみ） |
| `harvest_kw_*` | 収集キーワード候補 | 中身は汎用モメンタムに自動割当 |

これらは `uv run signalforge alt-data status` の「未実装」に表示されます。J-Quants 連携などは今後 `data_deps: credit_balance` に fetch を足す想定です。

## ダッシュボードの「—」表示

`implementation_map.yaml` で **approximation（代理）** が付いている戦略、または **data_deps のデータがまだ足りない** 戦略（例: 信用残・決算日不足）は、TSE 実験表の **期待値・損益比などを空白（—）** にします。誤って古い代理 BT の数字を見せないためです。**データ** 列に理由（代理BT、信用残未取得 等）が出ます。

## 重複 ID について

**同じテンプレ＋同じ params → BT 結果は完全一致** します。  
`harvest_kw_*` や株探プリセットの別名は、カタログ整理（統合）か、実データ実装後に **別ロジック** に切り替えない限り残ります。
