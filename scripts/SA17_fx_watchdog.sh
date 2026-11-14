#!/usr/bin/env bash
# SA17 FX acquisition with a gentler back-off than the script's own:
# no new file for 20 min -> stop, wait an hour, resume. At most 6 pauses per step.
set -u
A=runs/sa17_fx_20261107
LOG=runs/sa17_fx_20261107.chain.log
note() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
progress() { uv run python scripts/SA17_fx_progress.py "$A" "$1"; }
step() {
  local action=$1 dir=$2 pauses=0 state current expected last idle now pid rc
  state=$(progress "$dir") || return 1
  read -r current expected <<< "$state"
  while [ "$current" -lt "$expected" ]; do
    note "$action start: $current/$expected"
    last=$current; idle=0
    uv run python scripts/SA17_acquire_fx.py "$action" --archive "$A" >> "$LOG" 2>&1 &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
      sleep 60
      state=$(progress "$dir") || {
        note "$action: cannot read progress; stopping"
        pkill -P "$pid" 2>/dev/null
        kill "$pid" 2>/dev/null
        wait "$pid"
        return 1
      }
      read -r now expected <<< "$state"
      if [ "$now" -gt "$last" ]; then last=$now; idle=0; else idle=$((idle + 1)); fi
      if [ "$idle" -ge 20 ]; then
        note "$action idle 20 min: stopping"
        pkill -P "$pid" 2>/dev/null
        kill "$pid" 2>/dev/null
        break
      fi
    done
    wait "$pid"; rc=$?
    state=$(progress "$dir") || return 1
    read -r current expected <<< "$state"
    note "$action exit $rc: $current/$expected"
    [ "$current" -ge "$expected" ] && break
    pauses=$((pauses + 1))
    if [ "$pauses" -gt 6 ]; then note "$action: too many pauses, giving up"; return 1; fi
    note "$action pause 60 min ($pauses)"
    sleep 3600
  done
  return 0
}
main() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." || return 1
  note "watchdog: initial pause 40 min"
  sleep 2400
  step fetch hours || { tail -6 "$LOG"; return 1; }
  step verify minutes || { tail -6 "$LOG"; return 1; }
  uv run python scripts/SA17_acquire_fx.py build --archive "$A" >> "$LOG" 2>&1
  local rc=$?
  note "build exit $rc"
  tail -4 "$LOG"
  return "$rc"
}
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
