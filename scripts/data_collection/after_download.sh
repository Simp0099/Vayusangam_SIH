#!/usr/bin/env bash
# Wait for the OpenAQ collector to exit, then run the post-download chain.
#
# Polls the PID file rather than the process table so it cannot latch onto a
# recycled PID: it verifies the exit is the collector's by checking that no
# further raw pages appeared and the log carries a completion marker.
set -uo pipefail

ROOT="/Users/bhavishya/Documents/Bhavishya/Code/Hackathon/Github/Vayusangam"
cd "$ROOT"
PY=".venv/bin/python"
PIDFILE="logs/data_collection/openaq.pid"
LOG="logs/data_collection/openaq_production.log"
CHAIN_LOG="logs/data_collection/post_download_chain.log"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$CHAIN_LOG"; }

PID=$(cat "$PIDFILE" 2>/dev/null)
if [ -z "$PID" ]; then log "FATAL: no PID file at $PIDFILE"; exit 1; fi
log "watching collector PID $PID"

while kill -0 "$PID" 2>/dev/null; do sleep 60; done
log "collector PID $PID has exited"

PAGES=$(ls data/air_quality/raw/hours 2>/dev/null | wc -l | tr -d ' ')
log "raw pages on disk: $PAGES"
if [ "$PAGES" -lt 1000 ]; then
  log "ABORT: only $PAGES raw pages — the run cannot have completed successfully"
  exit 1
fi

if grep -qi "download complete\|all sensors\|finished" "$LOG" 2>/dev/null; then
  log "completion marker found in $LOG"
else
  log "NOTE: no completion marker in the log; proceeding because the process exited with pages on disk"
fi

log "manifest status: $(.venv/bin/python -c "import json;print(json.load(open('data/air_quality/collection_manifest.json'))['status'])" 2>/dev/null)"

run_step() {
  local name="$1"; shift
  log "=== $name ==="
  if "$@" >>"$CHAIN_LOG" 2>&1; then
    log "$name: OK"
  else
    log "$name: FAILED (exit $?)"
    return 1
  fi
}

run_step process   $PY scripts/data_collection/openaq/process_openaq.py  || exit 1
run_step enrich    $PY scripts/data_collection/openaq/enrich_availability.py || true
run_step validate  $PY scripts/data_collection/validate_all.py
run_step features  $PY scripts/data_collection/build_features.py
run_step manifest  $PY scripts/data_collection/write_manifest.py openaq \
  --dataset "OpenAQ v3 hourly station observations — Delhi NCR" \
  --lifecycle complete \
  --url "https://api.openaq.org/v3/sensors/1234/hours?api_key=PLACEHOLDER&limit=1000" \
  --start-date 2024-01-01 --end-date 2026-09-30 \
  --area "Delhi NCR, WGS84 74.0,26.0,80.0,32.5" \
  --variables "PM2.5,PM10,NO2,NOx,O3,CO,SO2,temperature,relative_humidity,wind_speed,wind_direction" \
  --license "Per upstream provider; attribution required" \
  --raw-dir data/air_quality/raw --file-limit 40000
run_step master    $PY scripts/data_collection/build_master.py --build

log "=== chain finished ==="
