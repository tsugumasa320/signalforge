#!/usr/bin/env bash
# 電源なし・蓋閉じでも BT 継続（sudo pmset + caffeinate）。完了後は restore-battery-sleep.sh。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export REFRESH_SERIES=1
export CLOSED_LID_BATTERY=1
exec "$ROOT/scripts/run-experiments-daemon.sh"
