#!/bin/bash
# CI / cron: fetch OHLCV once, advance diversified paper books from cache, export unified dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== SignalForge daily (multi-strategy) ==="

uv sync --extra dev --frozen 2>/dev/null || uv sync --extra dev

if [[ "${PUBLISH_ONLY:-}" == "1" ]]; then
  echo "--- publish only (paper books already computed) ---"
else
  echo "--- update paper-book universe (1d, append new bars) ---"
  uv run signalforge fetch --paper-books --timeframe 1d --update --with-correlations --workers 8

  echo "--- diversified paper (TSE forward, cached data) ---"
  uv run signalforge paper diversified-run-all --no-refresh --workers 8 || true
fi

echo "--- export unified dashboard ---"
uv run signalforge dashboard export --output _site
