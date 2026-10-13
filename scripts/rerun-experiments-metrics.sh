#!/usr/bin/env bash
# 期待値・最大DD 等の新指標を sidecar に載せるため、完了済み戦略を再BTする。
# 未完了戦略は従来どおり checkpoint から再開。実行中 BT がある場合は watch のみ。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export REFRESH_METRICS=1
exec "$ROOT/scripts/run-experiments-daemon.sh"
