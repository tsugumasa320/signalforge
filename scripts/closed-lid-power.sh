#!/usr/bin/env bash
# バッテリー駆動のまま蓋を閉じても Mac をスリープさせない（要 sudo）。
# BT 終了後は必ず closed_lid_power_off / restore-battery-sleep.sh で元に戻す。
set -euo pipefail

CLOSED_LID_PMSET_BACKUP="${CLOSED_LID_PMSET_BACKUP:-data/reports/.pmset-battery.backup}"
CLOSED_LID_PMSET_FLAG="${CLOSED_LID_PMSET_FLAG:-data/reports/.pmset-battery.closed-lid-on}"

_closed_lid_root() {
  if [[ -n "${ROOT:-}" ]]; then
    printf '%s' "$ROOT"
  else
    cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
  fi
}

_pmset_battery_get() {
  local key="$1"
  pmset -g custom 2>/dev/null | awk -v k="$key" '
    /^Battery Power:/ { inbat=1; next }
    inbat && /^[^ \t]/ { exit }
    inbat && $1 == k { print $2; exit }
  '
}

closed_lid_power_on() {
  if [[ "$(uname -s)" != Darwin ]]; then
    echo "closed-lid-power: macOS のみ"
    return 1
  fi
  local root
  root="$(_closed_lid_root)"
  mkdir -p "$root/data/reports"
  local backup="$root/$CLOSED_LID_PMSET_BACKUP"
  local flag="$root/$CLOSED_LID_PMSET_FLAG"

  if [[ -f "$flag" ]]; then
    echo "蓋閉じ用 pmset は既に ON（$flag）"
    return 0
  fi

  {
    echo "# saved $(date -Iseconds)"
    for key in sleep disablesleep standby powernap autopoweroff hibernatemode lowpowermode; do
      val="$(_pmset_battery_get "$key" || true)"
      [[ -n "$val" ]] && echo "${key}=${val}"
    done
  } > "$backup"

  echo "バッテリー時のスリープを抑止します（sudo が必要）…"
  sudo pmset -b sleep 0 disablesleep 1 standby 0 powernap 0 autopoweroff 0
  date -Iseconds > "$flag"
  echo "✅ 蓋閉じモード ON · 復帰: $root/scripts/restore-battery-sleep.sh"
  echo "   ⚠️ 発熱・消費電力が増えます。閉じた Mac をバッグ等に入れないでください。"
}

closed_lid_power_off() {
  if [[ "$(uname -s)" != Darwin ]]; then
    return 0
  fi
  local root
  root="$(_closed_lid_root)"
  local backup="$root/$CLOSED_LID_PMSET_BACKUP"
  local flag="$root/$CLOSED_LID_PMSET_FLAG"

  if [[ ! -f "$flag" ]]; then
    echo "蓋閉じ用 pmset は OFF です"
    return 0
  fi

  if [[ ! -f "$backup" ]]; then
    echo "バックアップがありません。既定値に近い設定へ戻します…"
    sudo pmset -b sleep 1 disablesleep 0 standby 1 powernap 1 autopoweroff 1
    rm -f "$flag"
    return 0
  fi

  echo "バッテリー pmset を復元します（sudo）…"
  local args=()
  while IFS='=' read -r key val; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    args+=("$key" "$val")
  done < "$backup"
  if ((${#args[@]} > 0)); then
    sudo pmset -b "${args[@]}"
  fi
  rm -f "$flag" "$backup"
  echo "✅ 蓋閉じモード OFF（通常のスリープ設定に戻しました）"
}
