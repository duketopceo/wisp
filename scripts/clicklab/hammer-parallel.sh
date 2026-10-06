#!/usr/bin/env bash
# hammer-parallel.sh — N CubeVM workers running clicklab suites in
# parallel. Each worker owns one sandbox (own chromium, own CDP), so
# there is no tab claiming between them. Hosted models bill the
# dedicated eval key via orch — if the matrix includes hosted specs
# and the WISP_ARENA_ORCH marker is missing, the script re-execs
# itself through orch.
#
#   hammer-parallel.sh [N] [MINUTES]   — default 2 workers, 60 min
#
# Sandboxes are left up for reuse (1h timeout); `cube.py down` kills.
set -u
cd "$(dirname "$0")/../.."
N=${1:-2}
MIN=${2:-60}
LOGDIR=~/.local/share/wisp/training-logs
mkdir -p "$LOGDIR"
END=$(( $(date +%s) + MIN * 60 ))

SUITES=("core:index.html" "dom-hard:index.html"
        "apps-chess:apps.html" "apps-settings:apps.html"
        "apps-email:apps.html" "apps-nodes:apps.html"
        "apps-editor:apps.html")
# one hosted spec max (arena policy); gemma is the cheap+strong pick
MODELS=("openrouter:google/gemma-4-31b-it")

# hosted matrix → re-exec under orch so spend bills the eval key and
# run.py's gate sees WISP_ARENA_ORCH=1 in the environment
HOSTED=0
for M in "${MODELS[@]}"; do
    case "$M" in openrouter:*|anthropic:*) HOSTED=1;; esac
done
if [ "$HOSTED" = 1 ] && [ "${WISP_ARENA_ORCH:-0}" != 1 ]; then
    echo "[hammer-par] hosted matrix — re-exec via orch"
    WISP_ARENA_ORCH=1 exec orch bash "$0" "$@"
fi

echo "[hammer-par] bringing up $N CubeVM workers"
ENDPOINTS=$(uv run python scripts/clicklab/cube.py up --count "$N" |
            grep -E '^[0-9]+ ')
echo "$ENDPOINTS"
if [ -z "$ENDPOINTS" ]; then
    echo "[hammer-par] cube.py up produced no endpoints" >&2
    exit 1
fi
mapfile -t LINES <<< "$ENDPOINTS"
if [ "${#LINES[@]}" -lt "$N" ]; then
    echo "[hammer-par] wanted $N workers, got ${#LINES[@]} endpoints" >&2
    exit 1
fi
declare -a W_IP W_PORT
for L in "${LINES[@]}"; do
    I=${L%% *}; REST=${L#* }
    W_IP[$I]=${REST%%:*}
    W_PORT[$I]=${REST##*:}
done
# sandbox ids from the state file (same order cube.py saved)
mapfile -t SIDS < <(python3 -c "
import json,os
st=json.load(open(os.path.expanduser('~/.local/share/wisp/cube-worker.json')))
print('\n'.join(w['sandbox_id'] for w in st.get('workers',[])))
")

worker() {
    local i=$1 ip=$2 port=$3 sid=$4
    local log="$LOGDIR/par-$(date +%Y%m%d-%H%M%S)-w$i.log"
    local seed=0
    while [ "$(date +%s)" -lt "$END" ]; do
        for M in "${MODELS[@]}"; do
            # round-robin suites offset by worker id for spread
            local idx=$(( (seed + i) % ${#SUITES[@]} ))
            local SP=${SUITES[$idx]}
            local S=${SP%%:*} P=${SP##*:}
            [ "$(date +%s)" -ge "$END" ] && break
            # a dead CDP endpoint means the sandbox is gone — fail
            # fast instead of burning every remaining task on it
            if ! curl -sf --max-time 5 \
                    "http://$ip:$port/json/version" >/dev/null; then
                echo "[w$i] CDP dead at $ip:$port — worker exiting" \
                    >>"$log"
                return
            fi
            echo "[w$i] suite=$S seed=$seed model=${M##*/}" >>"$log"
            uv run python scripts/clicklab/run.py --dom \
                --cdp "$ip:$port" --suite "$S" --page "$P" \
                --seed "$seed" --models "$M" \
                --worker "$i" --sandbox-id "$sid" >>"$log" 2>&1
            seed=$((seed + 1))
        done
    done
    echo "[w$i] time cap reached" >>"$log"
}

for i in $(seq 0 $((N - 1))); do
    worker "$i" "${W_IP[$i]}" "${W_PORT[$i]}" "${SIDS[$i]:-unknown}" &
    echo "[hammer-par] worker $i → ${W_IP[$i]}:${W_PORT[$i]} (${SIDS[$i]:-?})"
done
wait
echo "[hammer-par] all workers done — report:"
uv run python scripts/clicklab/report.py --since "$(date -d "@$((END - MIN * 60))" +%Y-%m-%dT%H:%M:%S)" 2>/dev/null || true
