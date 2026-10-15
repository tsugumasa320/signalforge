#!/bin/bash
# プライム全銘柄で分散ペーパー口座を init（長時間・並列 BT）
set -euo pipefail
cd "$(dirname "$0")/.."

LOG="data/logs/diversified-paper-prime.log"
mkdir -p data/logs

WORKERS="${WORKERS:-8}"
COHORT="${COHORT:-prime}"
STRATEGIES=(
  bb_lower_rsi_oversold
  bnf_multi_indicator_bounce
  grid_trading_range
  bnf_ma25_kairi_reversion
  mean_reversion_short_term
  low_pbr_value_reversal
  ichimoku_tk_cross
  gap_fill_reversal
  macd_cross
  ema_pullback
)

{
echo "=== $(date -Iseconds) diversified paper init cohort=$COHORT workers=$WORKERS ==="

for s in "${STRATEGIES[@]}"; do
  path="data/paper/diversified_swing_${s}.json"
  if [[ -f "$path" ]]; then
    rm -f "$path"
  fi
  echo "--- init $s ---"
  uv run signalforge paper diversified-init \
    --style swing \
    --strategy "$s" \
    --cohort "$COHORT" \
    --workers "$WORKERS"
done

echo "--- run-all ---"
uv run signalforge paper diversified-run-all --refresh --workers "$WORKERS"
echo "=== done $(date -Iseconds) ==="
} >>"$LOG" 2>&1
