#!/bin/bash
# 分散ペーパー口座を matrix 定義どおり init（長時間・並列 BT）
set -euo pipefail
cd "$(dirname "$0")/.."

LOG="data/logs/diversified-paper-prime.log"
mkdir -p data/logs

WORKERS="${WORKERS:-8}"

{
echo "=== $(date -Iseconds) diversified paper init-all workers=$WORKERS ==="
uv run signalforge paper diversified-init-all --force --workers "$WORKERS"
echo "--- run-all ---"
uv run signalforge paper diversified-run-all --refresh --workers "$WORKERS"
echo "=== done $(date -Iseconds) ==="
} >>"$LOG" 2>&1
