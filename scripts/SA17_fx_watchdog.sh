#!/usr/bin/env bash
# SA17 FX acquisition with a gentler back-off than the script's own:
# no new file for 20 min -> stop, wait an hour, resume. At most 6 pauses per step.
set -u
cd /home/paulr/projets/quant-backtester
A=runs/sa17_fx_20261107
LOG=runs/sa17_fx_20261107.chain.log
M=$A/manifest.jsonl
note() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
count() { find "$A/raw/$1" -type f -name '*.bi5' 2>/dev/null | wc -l; }
step() {
  local action=$1 expected=$2 dir=$3 pauses=0
  while [ "$(count "$dir")" -lt "$expected" ]; do
    note "$action start: $(count "$dir")/$expected"
    uv run python scripts/SA17_acquire_fx.py "$action" --archive "$A" >> "$LOG" 2>&1 &
    pid=$!
    last=$(wc -l < "$M"); idle=0
    while kill -0 "$pid" 2>/dev/null; do
      sleep 60
      now=$(wc -l < "$M")
      if [ "$now" -gt "$last" ]; then last=$now; idle=0; else idle=$((idle + 1)); fi
      if [ "$idle" -ge 20 ]; then
        note "$action idle 20 min: stopping"
        pkill -P "$pid" 2>/dev/null
        kill "$pid" 2>/dev/null
        break
      fi
    done
    wait "$pid"; rc=$?
    note "$action exit $rc: $(count "$dir")/$expected"
    [ "$(count "$dir")" -ge "$expected" ] && break
    pauses=$((pauses + 1))
    if [ "$pauses" -gt 6 ]; then note "$action: too many pauses, giving up"; return 1; fi
    note "$action pause 60 min ($pauses)"
    sleep 3600
  done
  return 0
}
note "watchdog: initial pause 40 min"
sleep 2400
step fetch 272 hours || { tail -6 "$LOG"; exit 1; }
step verify 48 minutes || { tail -6 "$LOG"; exit 1; }
uv run python scripts/SA17_acquire_fx.py build --archive "$A" >> "$LOG" 2>&1
rc=$?
note "build exit $rc"
tail -4 "$LOG"
exit $rc
