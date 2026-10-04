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
SUITE_IDX=0
SEED=0
MODELS=("openrouter:google/gemma-4-31b-it" "openrouter:google/gemini-2.5-flash")
MI=0
while [ "$(date +%s)" -lt "$END" ]; do
    SUITES=(core dom-hard)
    S=${SUITES[$((SUITE_IDX % 2))]}
    M=${MODELS[$((MI % 2))]}
    TS=$(date +%Y%m%d-%H%M%S)
    echo "[hammer] $TS suite=$S seed=$SEED model=$M"
    uv run python scripts/clicklab/run.py --dom --suite "$S" \
        --seed "$SEED" --models "$M" \
        > "$LOGDIR/run-$TS-$S-s$SEED.log" 2>&1
    TAIL=$(tail -2 "$LOGDIR/run-$TS-$S-s$SEED.log" | head -1)
    echo "[hammer] done: $TAIL"
    SUITE_IDX=$((SUITE_IDX + 1))
    MI=$((MI + 1))
    # bump seed after each full suite pair pass
    [ $((SUITE_IDX % 2)) -eq 0 ] && SEED=$((SEED + 1))
done
echo "[hammer] time cap reached"
