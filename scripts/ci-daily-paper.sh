#!/bin/bash
# CI / cron: fetch latest OHLCV and advance paper trading state.
set -euo pipefail
cd "$(dirname "$0")/.."

STYLE="${PAPER_STYLE:-swing}"
STRATEGY="${PAPER_STRATEGY:-macd_cross}"

echo "=== SignalForge daily paper ==="
echo "style=$STYLE strategy=$STRATEGY"

uv sync --extra dev --frozen 2>/dev/null || uv sync --extra dev

echo "--- fetch ---"
uv run signalforge fetch --ticker NVDA --timeframe 1d --refresh --with-correlations

echo "--- paper run ---"
uv run signalforge paper run --style "$STYLE" --strategy "$STRATEGY" --refresh

echo "--- status ---"
uv run signalforge paper status --style "$STYLE" --strategy "$STRATEGY"

echo "--- export dashboard ---"
uv run signalforge dashboard export --output _site --style "$STYLE" --strategy "$STRATEGY"
