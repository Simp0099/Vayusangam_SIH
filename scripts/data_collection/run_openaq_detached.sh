#!/bin/zsh
# Launch the OpenAQ production download fully detached so it survives closing the
# terminal. Same command as before: every page already cached under
# data/air_quality/raw/hours is reused, so this resumes rather than restarts.
cd /Users/bhavishya/Documents/Bhavishya/Code/Hackathon/Github/Vayusangam || exit 1
mkdir -p logs/data_collection
# nohup + setsid-style detachment: redirect all stdio to a file, ignore SIGHUP,
# and run in its own session so the controlling terminal's hangup never reaches it.
nohup .venv/bin/python scripts/data_collection/openaq/download_openaq.py \
  --start-date 2024-01-01 --end-date 2026-09-30 \
  >> logs/data_collection/openaq_production.log 2>&1 &
PID=$!
disown
echo "$PID" > logs/data_collection/openaq.pid
echo "detached pid: $PID"
