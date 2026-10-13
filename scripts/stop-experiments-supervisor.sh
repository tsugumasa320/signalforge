#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$ROOT/data/reports/experiments_supervisor.pid"

if [[ ! -f "$PIDFILE" ]]; then
  echo "監視 PID ファイルがありません。"
  exit 0
fi
pid="$(cat "$PIDFILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid" 2>/dev/null || true
  echo "監視を停止しました (PID $pid)"
else
  echo "監視プロセスは既に停止しています。"
fi
rm -f "$PIDFILE"
