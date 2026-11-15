# AI×トレード・トライアル

SignalForge の既存出力を AI に渡し、**要約 → 採点 → 議論**の順で試す。発注には接続しない。

## 前提

```bash
uv run signalforge trend-screen ranking   # data/published/trend_screen_ranking.json
# 任意: paper / diversified / tse_strategy_summary もあればパケットに載る
```

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

## GitHub Pages（本番のダッシュボード）

公開ハブ: https://tsugumasa320.github.io/signalforge/ → **AIトライアル**（`ai/index.html`）

`data/ai/` は gitignore のため、Pages に載るのは **`data/published/ai_*.json`** だけ。

```bash
uv run signalforge ai save-response brief examples/ai_brief_response.json
# → data/published/ai_brief_response.json も更新される
# 同様に score / debate
git add data/published/ai_*.json && git commit   # ユーザーが明示したとき
uv run signalforge dashboard export --output _site
```

日次 Actions（`dashboard export`）でも `ai/index.html` が生成される。published JSON が commit されていれば Pages に出る。

ローカル Streamlit にも **AIトライアル** タブがある（確認用）。

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
