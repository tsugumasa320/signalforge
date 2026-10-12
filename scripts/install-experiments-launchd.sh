#!/usr/bin/env bash
# macOS launchd に夜間 experiments 再開ジョブを登録（パスを plist に埋め込み）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$ROOT/scripts/com.signalforge.experiments.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.signalforge.experiments.plist"
sed "s|REPLACE_WITH_REPO|$ROOT|g" "$PLIST_SRC" > "$PLIST_DST"
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
echo "Loaded: $PLIST_DST"
echo "ログ: $ROOT/data/reports/experiments_launchd.log"
echo "手動: launchctl start com.signalforge.experiments"
