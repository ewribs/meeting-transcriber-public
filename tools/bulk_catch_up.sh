#!/bin/bash
# Overnight catch-up: rebuild every older meeting with names (newest first).
# Nothing is applied to your meetings; apply-all is a separate morning step.
# Safe to stop (Ctrl-C) and run again: finished meetings are skipped.
cd "$(dirname "$0")/.." || exit 1
LOG="$HOME/Library/Application Support/Meeting Transcriber/catch_up_run.log"
mkdir -p "$(dirname "$LOG")"
PY="${PYTHON:-python3}"
{
  echo "=== started $(date) ==="
  # three passes: a meeting that failed (for example a model hiccup) gets two more tries
  for attempt in 1 2 3; do
    echo "--- pass $attempt $(date) ---"
    caffeinate -i "$PY" catch_up.py rebuild-all
  done
  echo "=== finished $(date) ==="
  "$PY" catch_up.py list | sed 's/^.*: //' | sort | uniq -c
} 2>&1 | tee -a "$LOG"
