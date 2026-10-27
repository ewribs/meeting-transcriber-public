#!/bin/bash
# Model benchmark: rebuild five meetings with each model, into separate staging
# folders. Nothing in your real meetings is changed. Safe to stop and run again
# (finished models are skipped; delete a folder under private_benchmarks/model_bench to redo it).
cd "$(dirname "$0")/../.." || exit 1
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY="$HOME/Projects/meeting-transcriber/.venv/bin/python"
OUT="$PWD/private_benchmarks/model_bench"
PREFIXES="2026-10-26_1002 2026-10-26_0958 2026-10-23_1207 2026-10-23_1202 2026-10-23_0956"
MODELS="baseline=Qwen/Qwen3-30B-A3B-MLX-6bit qwen38=mlx-community/Qwen3.8-27B-4bit mistral=mlx-community/Mistral-Small-3.2-24B-Instruct-2506-4bit"
NAMES=$("$PY" - $PREFIXES <<'PYEOF'
import sys, config
from catch_up import all_runs
runs = all_runs(config.OUTPUT_DIR)
print(" ".join(n for p in sys.argv[1:] for n in runs if n.startswith(p)))
PYEOF
)
echo "meetings: $NAMES"
for pair in $MODELS; do
  tag="${pair%%=*}"; model="${pair#*=}"
  [ -f "$OUT/$tag/DONE" ] && { echo "$tag already done"; continue; }
  mkdir -p "$OUT/$tag"
  echo "=== $tag ($model) $(date) ==="
  start=$(date +%s)
  for name in $NAMES; do
    t0=$(date +%s)
    MT_MLX_MODEL="$model" caffeinate -i "$PY" catch_up.py rebuild "$name" --staging-dir "$OUT/$tag" 2>&1 | tail -3
    echo "$name $(( $(date +%s) - t0 ))" >> "$OUT/$tag/seconds.txt"
  done
  echo "total $(( $(date +%s) - start ))" >> "$OUT/$tag/seconds.txt"
  touch "$OUT/$tag/DONE"
done
echo "=== finished $(date) ==="
cat "$OUT"/*/seconds.txt
