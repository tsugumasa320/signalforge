#!/bin/bash
# CI / cron: fetch OHLCV, run all paper strategies, export unified dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== SignalForge daily (multi-strategy) ==="

uv sync --extra dev --frozen 2>/dev/null || uv sync --extra dev

echo "--- fetch swing (1d) ---"
uv run signalforge fetch --ticker NVDA --timeframe 1d --refresh --with-correlations

echo "--- fetch daytrade (5m) ---"
uv run signalforge fetch --ticker NVDA --timeframe 5m --refresh || echo "5m fetch skipped (Alpaca/yfinance limit)"

echo "--- paper run-all ---"
uv run signalforge paper run-all --refresh

echo "--- export unified dashboard ---"
uv run signalforge dashboard export --output _site
