#!/usr/bin/env bash
# Run the gauntlet unattended on a separate host, never on the owner's laptop.
#
#   scripts/gauntlet/remote.sh [--host H] [--ref REF] [--] [gauntlet.py args]
#
# 1. Syncs the host checkout (default ~/wisp-gauntlet) to REF (default
#    origin/master) with a plain fetch + detached checkout.
# 2. Starts the isolated Hyprland session there, runs scripts/gauntlet.py
#    with --session isolated, and stops the session afterwards.
# 3. Copies the new run directory back to
#    ~/.local/share/wisp-gauntlet/runs/.
#
# The eval key is read locally (default `omaseal get openrouter
# orchestral`, override with WISP_GAUNTLET_KEY_CMD) and travels ONLY over
# the ssh stdin pipe: the remote shell reads it into a variable and
# exports it to the gauntlet process alone. It is never in any argv, file,
# env file or shell history, on either machine. The host holds no secrets.
#
# The host comes from --host or $WISP_GAUNTLET_HOST (an ssh destination).
# $WISP_GAUNTLET_CHECKOUT overrides the remote checkout path.
# Exit: 0 finished, 2 usage/precondition (no key, no host), else the
# gauntlet's own code.
set -euo pipefail

host="${WISP_GAUNTLET_HOST:-}"
ref="origin/master"
checkout="${WISP_GAUNTLET_CHECKOUT:-wisp-gauntlet}"
key_cmd="${WISP_GAUNTLET_KEY_CMD:-omaseal get openrouter orchestral}"
local_runs="${WISP_GAUNTLET_LOCAL_RUNS:-$HOME/.local/share/wisp-gauntlet/runs}"

die() { echo "remote.sh: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host) [ $# -ge 2 ] || die "--host needs a value"; host="$2"; shift 2 ;;
    --ref) [ $# -ge 2 ] || die "--ref needs a value"; ref="$2"; shift 2 ;;
    --) shift; break ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) break ;;
  esac
done

[ -n "$host" ] || die "no host: pass --host or set WISP_GAUNTLET_HOST"
[[ "$host" =~ ^[A-Za-z0-9._@:-]+$ ]] || die "bad host name"
[[ "$host" != -* ]] || die "bad host name"
[[ "$ref" =~ ^[A-Za-z0-9._/-]+$ ]] || die "bad ref"
[[ "$checkout" =~ ^[A-Za-z0-9._/-]+$ ]] || die "bad checkout path"

# gauntlet args are quoted once for the remote bash -c; none may be a key
gargs=""
for a in "$@"; do gargs+=" $(printf '%q' "$a")"; done

# The key is fetched before anything touches the host, so a locked or
# missing key fails fast with nothing started.
key="$(bash -c "$key_cmd" 2>/dev/null)" || die "could not read the eval key"
[ -n "$key" ] || die "the eval key is empty"

ssh_opts=(-o BatchMode=yes -o ConnectTimeout=20)

# Run a script on the host under bash, whatever the login shell is. The
# script travels base64-encoded in argv (it never holds the key); stdin
# stays free for the caller.
rbash() {
  local b64
  b64="$(printf '%s' "$1" | base64 -w0)"
  ssh "${ssh_opts[@]}" "$host" "bash -c 'eval \"\$(printf %s $b64 | base64 -d)\"'"
}

# 1. sync (no key involved)
rbash "set -e
cd \"\$HOME/$checkout\"
git fetch -q origin
r='$ref'
r=\"\${r#origin/}\"
git fetch -q origin \"\$r\"
git checkout -q --detach FETCH_HEAD
git log --oneline -1" </dev/null || die "could not sync the host checkout"

# 2. run: the key is the first stdin line, read into a shell variable
# and set in the environment of the gauntlet process only.
remote_script="set -u
cd \"\$HOME/$checkout\"
IFS= read -r k
# nested mode starts from the host's logged-in seat: an ssh shell has no
# session variables, so find them (headless needs aquamarine AQ_BACKENDS,
# which the host's build lacks)
export XDG_RUNTIME_DIR=\"/run/user/\$(id -u)\" WAYLAND_DISPLAY=wayland-1 XDG_SESSION_TYPE=wayland
export HYPRLAND_INSTANCE_SIGNATURE=\"\$(ls -t \"\$XDG_RUNTIME_DIR/hypr\" | grep -v lock | head -1)\"
# the nested window sometimes does not map in time on slow GPUs: retry
up=0
for i in 1 2 3; do
  if python3 scripts/isolated_session.py start >&2; then up=1; break; fi
  python3 scripts/isolated_session.py stop >&2 || true
done
[ \"\$up\" = 1 ] || exit 2
rc=0
OPENROUTER_API_KEY=\"\$k\" python3 scripts/gauntlet.py --session isolated$gargs || rc=\$?
unset k
python3 scripts/isolated_session.py stop >&2 || true
exit \$rc"
rc=0
printf '%s\n' "$key" | rbash "$remote_script" || rc=$?
unset key

# 3. copy back the newest run directory
mkdir -p "$local_runs"
latest="$(rbash 'cd "$HOME/.local/share/wisp-gauntlet/runs" 2>/dev/null && ls -1t | head -1' </dev/null || true)"
if [[ "$latest" =~ ^gauntlet-[A-Za-z0-9._-]+$ ]]; then
  rbash "tar -C \"\$HOME/.local/share/wisp-gauntlet/runs\" -cf - $latest" </dev/null \
    | tar -C "$local_runs" -xf -
  echo "run copied to $local_runs/$latest" >&2
fi
exit "$rc"
