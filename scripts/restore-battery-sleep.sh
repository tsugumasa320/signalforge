#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/closed-lid-power.sh
source "$ROOT/scripts/closed-lid-power.sh"
closed_lid_power_off
