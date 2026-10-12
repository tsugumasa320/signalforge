#!/usr/bin/env bash
# 途中停止後に TSE 実験を再開（checkpoint / 完了済み戦略 JSON を利用）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data/reports
LOG=data/reports/experiments_run.log
echo "=== experiments $(date -Iseconds) resume ===" >> "$LOG"
# 既存 JSON を compact（nested metrics 削除・sidecar 分離）
uv run signalforge experiments compact >> "$LOG" 2>&1 || true
uv run signalforge experiments aggregate >> "$LOG" 2>&1 || true
exec uv run signalforge experiments run --ignore-schedule --workers 8 >> "$LOG" 2>&1
