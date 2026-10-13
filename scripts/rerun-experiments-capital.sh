#!/usr/bin/env bash
# 口座サイズ・ポジション上限などを変えたあと、古い backtest_capital の戦略だけ再BTする。
# 例: INITIAL_CASH_JPY=5000000 MAX_POSITION_PCT=0.25 ./scripts/rerun-experiments-capital.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export REFRESH_CAPITAL=1
exec "$ROOT/scripts/run-experiments-daemon.sh"
