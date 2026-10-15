#!/usr/bin/env bash
# shellcheck disable=SC1091
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
uv run signalforge experiments status 2>/dev/null || true
