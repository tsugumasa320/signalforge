#!/usr/bin/env bash
# 代替データ付き戦略: データ取得 → 旧結果削除 → 実験再開
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== alt-data fetch (sectors + earnings) ==="
uv run signalforge alt-data fetch --all "$@"

echo "=== invalidate experiment JSON for data_deps strategies ==="
uv run signalforge alt-data invalidate-experiments

echo "=== resume experiments ==="
exec ./scripts/run-experiments-daemon.sh
