#!/usr/bin/env bash
# TSE 実験をバックグラウンド起動し、このターミナルでは live 進捗を表示
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data/reports
LOG=data/reports/experiments_run.log
PIDFILE=data/reports/experiments.pid
WATCH_INTERVAL="${WATCH_INTERVAL:-5}"

if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    echo "既に実行中 (PID $old). このターミナルで進捗だけ表示します。"
    echo ""
    exec uv run signalforge experiments watch --interval "$WATCH_INTERVAL"
  fi
fi

export PYTHONUNBUFFERED=1
echo "=== experiments daemon $(date -Iseconds) ===" >> "$LOG"

nohup bash -c "
  cd \"$(pwd)\"
  export PYTHONUNBUFFERED=1
  uv run signalforge experiments compact >> \"$LOG\" 2>&1 || true
  uv run signalforge experiments aggregate >> \"$LOG\" 2>&1 || true
  if command -v caffeinate >/dev/null 2>&1; then
    exec caffeinate -i uv run signalforge experiments run --ignore-schedule --workers 8
  else
    exec uv run signalforge experiments run --ignore-schedule --workers 8
  fi
" >> "$LOG" 2>&1 &

wrapper_pid=$!
echo "$wrapper_pid" > "$PIDFILE"

for _ in $(seq 1 60); do
  py_pid="$(pgrep -f "/signalforge experiments run" 2>/dev/null | tail -1 || true)"
  if [[ -n "$py_pid" ]]; then
    echo "$py_pid" > "$PIDFILE"
    echo "BT 開始 PID $py_pid  ·  ログ: $LOG"
    break
  fi
  sleep 1
done

echo ""
exec uv run signalforge experiments watch --interval "$WATCH_INTERVAL"
