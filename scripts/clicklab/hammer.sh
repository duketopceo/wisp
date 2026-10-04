#!/usr/bin/env bash
# hammer.sh — mass clicklab training runs.
# Loops suites x seeds in --dom mode (background-safe, no focus needs),
# capturing every run's stdout to training-logs/ and records to
# ~/.local/share/wisp/clicklab.jsonl.
#
#   hammer.sh [MINUTES]   — default 60 min, then stops
set -u
cd "$(dirname "$0")/../.."
MIN=${1:-60}
LOGDIR=~/.local/share/wisp/training-logs
mkdir -p "$LOGDIR"
END=$(( $(date +%s) + MIN * 60 ))
SUITES=(core dom-hard)
MODELS=("openrouter:google/gemma-4-31b-it" "openrouter:google/gemini-2.5-flash")
SEED=0
while [ "$(date +%s)" -lt "$END" ]; do
    for M in "${MODELS[@]}"; do
        for S in "${SUITES[@]}"; do
            [ "$(date +%s)" -ge "$END" ] && break 2
            TS=$(date +%Y%m%d-%H%M%S)
            TAG=${M##*/}
            echo "[hammer] $TS suite=$S seed=$SEED model=$TAG"
            uv run python scripts/clicklab/run.py --dom --suite "$S" \
                --seed "$SEED" --models "$M" \
                > "$LOGDIR/run-$TS-$S-s$SEED-$TAG.log" 2>&1
            TAIL=$(tail -2 "$LOGDIR/run-$TS-$S-s$SEED-$TAG.log" | head -1)
            echo "[hammer] done: $TAIL"
        done
    done
    SEED=$((SEED + 1))
done
echo "[hammer] time cap reached"
