#!/usr/bin/env bash
# TSE 実験をバックグラウンド起動し、このターミナルでは live 進捗を表示
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data/reports
LOG=data/reports/experiments_run.log
PIDFILE=data/reports/experiments.pid
WATCH_INTERVAL="${WATCH_INTERVAL:-5}"
REFRESH_METRICS="${REFRESH_METRICS:-0}"
REFRESH_SERIES="${REFRESH_SERIES:-0}"
REFRESH_CAPITAL="${REFRESH_CAPITAL:-0}"
RUN_EXTRA=()
if [[ "$REFRESH_METRICS" == "1" ]]; then
  RUN_EXTRA+=(--refresh-metrics)
  echo "モード: 指標更新（完了戦略を期待値・最大DD 付きで再BT）"
fi
if [[ "$REFRESH_SERIES" == "1" ]]; then
  RUN_EXTRA+=(--refresh-series)
  echo "モード: 系列追記（期間スライス用 trades_compact / equity_daily）"
fi
if [[ "$REFRESH_CAPITAL" == "1" ]]; then
  RUN_EXTRA+=(--refresh-capital)
  echo "モード: 資金条件更新（backtest_capital 不一致の完了戦略を再BT）"
fi
if [[ -n "${INITIAL_CASH_JPY:-}" ]]; then
  RUN_EXTRA+=(--initial-cash-jpy "$INITIAL_CASH_JPY")
fi
if [[ -n "${MAX_POSITION_PCT:-}" ]]; then
  RUN_EXTRA+=(--max-position-pct "$MAX_POSITION_PCT")
fi
if [[ -n "${MIN_CASH_RESERVE_PCT:-}" ]]; then
  RUN_EXTRA+=(--min-cash-reserve-pct "$MIN_CASH_RESERVE_PCT")
fi

if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  running_pid="$(pgrep -f "signalforge experiments run" 2>/dev/null | tail -1 || true)"
  if [[ -n "$running_pid" ]]; then
    echo "$running_pid" > "$PIDFILE"
    echo "既に実行中 (PID $running_pid). このターミナルで進捗だけ表示します。"
    echo ""
    exec uv run signalforge experiments watch --interval "$WATCH_INTERVAL"
  fi
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    echo "既に実行中 (PID $old). このターミナルで進捗だけ表示します。"
    echo ""
    exec uv run signalforge experiments watch --interval "$WATCH_INTERVAL"
  fi
  rm -f "$PIDFILE"
fi

export PYTHONUNBUFFERED=1
echo "=== experiments daemon $(date -Iseconds) ===" >> "$LOG"

nohup bash -c "
  cd \"$(pwd)\"
  export PYTHONUNBUFFERED=1
  uv run signalforge experiments compact >> \"$LOG\" 2>&1 || true
  uv run signalforge experiments aggregate >> \"$LOG\" 2>&1 || true
  if command -v caffeinate >/dev/null 2>&1; then
    exec caffeinate -i uv run signalforge experiments run --ignore-schedule --workers 8 ${RUN_EXTRA[*]:-}
  else
    exec uv run signalforge experiments run --ignore-schedule --workers 8 ${RUN_EXTRA[*]:-}
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
