#!/usr/bin/env bash
# 途中停止後に TSE 実験を再開（checkpoint / 完了済み戦略 JSON を利用）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/run-experiments-daemon.sh"
