#!/usr/bin/env bash
# Rebuild the Wisp flame asset (assets/brand/wisp-flame) from its build script.
#
# Blender has no Linux ARM64 build, so the scene is built and rendered on a Mac
# with Blender installed (default host luke-pro-max1, Homebrew cask), then the
# outputs are copied back and assembled here.
#
#   scripts/brand/render_wisp_flame.sh [--host HOST] [--frames N]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ASSET="$ROOT/assets/brand/wisp-flame"
HOST="${WISP_FLAME_HOST:-luke-pro-max1}"
BLENDER="${WISP_FLAME_BLENDER:-/opt/homebrew/bin/blender}"
FRAMES=48
while [ $# -gt 0 ]; do
  case $1 in
    --host) HOST=$2; shift ;;
    --frames) FRAMES=$2; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

# A fresh remote directory per run, so two renders on one host never share it.
REMOTE="$(ssh -o BatchMode=yes "$HOST" 'mktemp -d /tmp/wisp-flame-build.XXXXXX')"
LOCAL="$(mktemp -d)"
trap 'rm -rf "$LOCAL"; ssh -o BatchMode=yes "$HOST" "rm -rf $REMOTE" || true' EXIT

scp -q "$ASSET/source/build_flame.py" "$HOST:$REMOTE/"
ssh -o BatchMode=yes "$HOST" "$BLENDER --background --factory-startup --python $REMOTE/build_flame.py -- --out $REMOTE/out --frames $FRAMES" \
  | grep -E "wisp-flame: done|Error|Traceback" || true
scp -rq "$HOST:$REMOTE/out" "$LOCAL/"
[ -f "$LOCAL/out/wisp-flame.glb" ] || { echo "render failed: no glb" >&2; exit 1; }

install -D -m 0644 "$LOCAL/out/wisp-flame.blend" "$ASSET/source/wisp-flame.blend"
install -D -m 0644 "$LOCAL/out/wisp-flame.glb" "$ASSET/export/wisp-flame.glb"
python3 "$ROOT/scripts/brand/assemble_wisp_flame.py" "$LOCAL/out" "$ASSET/export"
echo "wisp-flame: exports updated in $ASSET"
