#!/usr/bin/env bash
# TSE 実験 BT が落ちたら自動で experiments run を再開する監視（バックグラウンド）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data/reports

PIDFILE=data/reports/experiments_supervisor.pid
LOG=data/reports/experiments_supervisor.log
INTERVAL="${SUPERVISOR_INTERVAL:-60}"
MODE="${SUPERVISOR_MODE:-auto}" # auto | campaign | metrics
WORKERS="${EXPERIMENTS_SUPERVISOR_WORKERS:-0}"

if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    echo "監視は既に起動中 (PID $old)"
    echo "ログ: $LOG"
    exit 0
  fi
fi

export PYTHONUNBUFFERED=1
nohup uv run signalforge experiments supervise \
  --interval "$INTERVAL" \
  --mode "$MODE" \
  --workers "$WORKERS" \
  >> "$LOG" 2>&1 &

echo "$!" > "$PIDFILE"
echo "✅ 監視起動 PID $(cat "$PIDFILE")  ·  ${INTERVAL}s 間隔  mode=$MODE"
echo "   BT ログ: data/reports/experiments_run.log"
echo "   監視ログ: $LOG"
echo "   停止: ./scripts/stop-experiments-supervisor.sh"
