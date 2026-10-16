#!/bin/bash
# CI / cron: fetch OHLCV, run all paper strategies, export unified dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== SignalForge daily (multi-strategy) ==="

uv sync --extra dev --frozen 2>/dev/null || uv sync --extra dev

echo "--- fetch Japan universe (1d) ---"
uv run signalforge fetch --universe japan_liquid --timeframe 1d --refresh --with-correlations

echo "--- diversified paper (TSE forward) ---"
uv run signalforge paper diversified-run-all --refresh --workers 8 || true

echo "--- export unified dashboard ---"
uv run signalforge dashboard export --output _site
