#!/usr/bin/env bash
# 途中停止後に TSE 実験を再開（checkpoint / 完了済み戦略 JSON を利用）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data/reports
echo "=== experiments $(date -Iseconds) resume ===" >> data/reports/experiments_run.log
exec uv run signalforge experiments run --ignore-schedule --workers 8 >> data/reports/experiments_run.log 2>&1
