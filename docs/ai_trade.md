# AI×トレード・トライアル

SignalForge の既存出力を AI に渡し、**要約 → 採点 → 議論**の順で試す。発注には接続しない。

## 前提

```bash
uv run signalforge trend-screen ranking   # data/published/trend_screen_ranking.json
# 任意: paper / diversified / tse_strategy_summary もあればパケットに載る
# 推奨: 決算カレンダー（Score の event 因子）
uv run signalforge alt-data fetch --earnings   # data/alt/earnings/*.json
# JQUANTS_API_KEY があれば J-Quants カレンダー、無ければ yfinance（いずれもローカルキャッシュ）
```

Score / Brief / Debate の `earnings_next*` は ranking 行を優先し、欠けていれば `data/alt/earnings` から補完する（ライブ API は呼ばない）。キャッシュも無い銘柄は `event_data=missing` で event 因子を中立点にする。

**PIT（薄い可視性ゲート）:** `as_of` より後のサプライズ開示日・ニュース `published_at` は採点前に除外する（KabuForge 風の available_at チェック）。完全な歴史 PIT 認証ではない。パケットに `pit_coverage` / 候補の `pit_ok`・`pit_issues` が付く。

## コマンド

```bash
# Phase 1 — 日次ブリーフィング用パケット
uv run signalforge ai brief
# → data/ai/brief_latest.json
# → data/ai/brief_prompt.md

# Phase 2 — 上位銘柄の採点パケット
uv run signalforge ai score --top 20
# → data/ai/scores_latest.json
# → data/ai/score_prompt.md

# Phase 3 — 少数銘柄のブル／ベア議論（自前プロンプト）
uv run signalforge ai debate --top 3
uv run signalforge ai debate --from-scores --top 3
uv run signalforge ai debate --tickers 4588.T,6098.T

# 返答JSONの保存
uv run signalforge ai save-response brief /path/to/reply.json
uv run signalforge ai save-response score /path/to/reply.json --as-of 2026-11-13
uv run signalforge ai save-response debate /path/to/reply.json
```

プロンプト本体: [`prompts/ai_brief.md`](../prompts/ai_brief.md) / [`ai_score.md`](../prompts/ai_score.md) / [`ai_debate.md`](../prompts/ai_debate.md)

返答例（フォーマット確定用）: [`examples/ai_brief_response.json`](../examples/ai_brief_response.json) / [`ai_score_response.json`](../examples/ai_score_response.json) / [`ai_debate_response.json`](../examples/ai_debate_response.json)

## 日次自動（推奨）

ルールベース（LLM API 不要）で Brief / Score / Debate を生成し、ADOPT を採択ログに残して 5日・20日リターンを集計する。

```bash
uv run signalforge trend-screen ranking   # 材料
uv run signalforge ai daily               # 生成 + published 更新 + adoption eval（ニュース見出しも取得）
uv run signalforge ai daily --no-fetch-news  # キャッシュのみ
uv run signalforge ai market              # 地合い（日経/TOPIX/ダウ/S&P/NASDAQ）
uv run signalforge ai discover            # トレンド通過なしで流動性ユニバースから発掘
uv run signalforge ai evaluate-adoptions  # 成績だけ再計算

# 承認ゲート（TradingAgents / ai-hedge-fund 系の「人が最終確認」）
uv run signalforge ai pending             # ADOPT 提案の一覧
uv run signalforge ai approve 7203.T      # 承認（発注しない・台帳に記録）
uv run signalforge ai reject 6758.T --note "過熱"
uv run signalforge ai ledger              # hash 連鎖の監査台帳
```

`ai daily` は ADOPT を **提案**として `data/published/ai_approvals.json` に pending 登録し、決定を `ai_ledger.json`（hash 連鎖）へ追記する。

フォワード成績（`ai_adoption_eval.json`）は2層:

| キー | 意味 |
|------|------|
| `summary` | 提案全体（システム性能） |
| `summary_approved` | **approved のみ**（人がゲートした paper intent。発注なし） |

各行に `gate`（pending/approved/rejected/ungated）と `paper_intent`（approved なら true）が付く。

承認直後は 5営業日・20営業日のフォワードリターンがまだ埋まらない。`ai evaluate-adoptions`（および日次 CI の `ai daily`）は不足分を毎回再計算するが、`as_of` から十分な営業日が経つまで各行は `status_5d` / `status_20d` = `pending` のままになる。ゲート処理後は数営業日待ち、Pages の Adoption 成績または `uv run signalforge ai evaluate-adoptions` で埋まり具合を確認する。

**内容（日付だけではない）**

| ソース | パス | 使い方 |
|--------|------|--------|
| 決算サプライズ | `data/earnings_surprise/fins/*.parquet` | 会社予想上方 / C0 / 営業利益 YoY（コンセンサス比はなし） |
| ニュース見出し | `data/alt/news/*.json` | Yahoo 見出し。`ai daily` または `ai score --fetch-news` で取得 |


GitHub Actions（`scripts/ci-daily-paper.sh`）が ranking / forward の後に `ai daily` を回し、`data/published/ai_*.json` を commit する。

## Discord 通知

`ai daily` のあと、ADOPT と「人がやること」を Discord に送る（Webhook URL があるときだけ）。

1. Discord チャンネル → 設定 → 連携サービス → ウェブフック → URL をコピー
2. ローカル: `.env` に `DISCORD_WEBHOOK_URL=...`
3. GitHub: repo Secrets に `DISCORD_WEBHOOK_URL` を追加（日次 Actions が読む）

```bash
uv run signalforge ai notify-discord --dry-run   # 文面だけ確認
uv run signalforge ai notify-discord             # 送信
uv run signalforge ai daily                      # 生成と同時に送信（既定）
uv run signalforge ai daily --no-discord         # 送信なし
```

## GitHub Pages（本番のダッシュボード）

公開ハブ: https://tsugumasa320.github.io/signalforge/ai/

載るもの: **地合い** / Brief / Score / Debate / **Approval** / **Ledger** / **Adoption 成績**
（`market_regime.json` · `ai_approvals.json` · `ai_ledger.json` · `ai_adoption_log.json` · `ai_adoption_eval.json`）

### 地合い（Market regime）

`ai market` / `ai daily` が現金指数と先物の 1/5/20日リターン・移動平均位置からラベルを付ける。Brief の `market_take` にも要約を載せる。マクロ予測ではなく簡易スナップショット。

| ラベル | 意味（目安） |
|--------|----------------|
| `risk_on` | 強気。20日おおむね上昇かつ200日線の上 → リスク資産に資金が向きやすい |
| `mixed_on` | やや強気（指数間でバラつき） |
| `mixed` | まちまち。方向感が薄い |
| `mixed_off` | やや弱気 |
| `risk_off` | 弱気。20日おおむね下落かつ200日線の下 → 守り寄りになりやすい |

現金: 日経1321 / TOPIX1306 / ダウ / S&P / NASDAQ。先物: `NIY=F`（日経）/ `YM=F` / `ES=F` / `NQ=F`。

手動で LLM 返答を使う場合:

```bash
uv run signalforge ai save-response brief /path/to/reply.json
```

## Cursor での回し方

1. `ai brief`（または score / debate）を実行
2. このチャットで「`data/ai/brief_latest.json` と `brief_prompt.md` に従って」と依頼
3. 返ってきた JSON を `ai save-response` で保存（published も更新）
4. published を commit → Pages / export で確認
5. 採用／無視／結果をメモし、1週間後に残すか決める

## やらないこと

- TradingView Webhook（無料プラン不可）
- 10個の外部リポ一括導入
- 自動発注

TradingAgents 等の外部委員会ツールは米国前提が多いため、日本株は本リポの `ai debate` を使う。
取り入れたのは **役割ラベル（bull/bear/risk/human）・承認ゲート・hash 台帳・薄い PIT ゲート** のみ（丸ごと導入しない）。
銘柄コード表示は Yahoo!ファイナンス日本版へのリンク（Pages / ペーパー約定表 / TSE 銘柄別など）。
