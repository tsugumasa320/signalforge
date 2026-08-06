#!/bin/bash
# Double-click in Finder to launch SignalForge dashboard (background daemon).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export ARROW_DEFAULT_MEMORY_POOL=system

echo "=== SignalForge Dashboard ==="
echo "Project: $ROOT"

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  uv sync --extra dev
fi

.venv/bin/signalforge dashboard start
