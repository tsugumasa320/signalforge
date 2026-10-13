#!/usr/bin/env bash
# 期間スライス用に trades_compact / equity_daily を sidecar へ追記（欠けている銘柄だけ再BT）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export REFRESH_SERIES=1
exec "$ROOT/scripts/run-experiments-daemon.sh"
