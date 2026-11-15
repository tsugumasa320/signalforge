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
uv run signalforge ai discover            # トレンド通過なしで流動性ユニバースから発掘
uv run signalforge ai evaluate-adoptions  # 成績だけ再計算
```

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

載るもの: Brief / Score / Debate / **Adoption 成績**（`ai_adoption_log.json` · `ai_adoption_eval.json`）

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
