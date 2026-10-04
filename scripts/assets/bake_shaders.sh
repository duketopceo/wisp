#!/usr/bin/env bash
# Bake assets/shaders/*.frag into shell-plugin/shaders/*.frag.qsb (the
# plugin directory is what `wispd install` copies) and record each source
# hash in assets/shaders/<name>.frag.sha256 so tests/test_assets_baked.py
# can tell when the committed .qsb is stale.
#   scripts/assets/bake_shaders.sh          bake and write hashes
#   scripts/assets/bake_shaders.sh --check  exit 1 if a hash is stale
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
src="$root/assets/shaders"
out="$root/shell-plugin/shaders"
qsb="${QSB:-$(command -v qsb || true)}"
[ -z "$qsb" ] && [ -x /usr/lib/qt6/bin/qsb ] && qsb=/usr/lib/qt6/bin/qsb
rc=0
mkdir -p "$out"
for f in "$src"/*.frag; do
  name="$(basename "$f")"
  sum="$(sha256sum "$f" | cut -d' ' -f1)"
  if [ "${1:-}" = "--check" ]; then
    [ "$(cat "$src/$name.sha256" 2>/dev/null)" = "$sum" ] || { echo "stale: $name"; rc=1; }
    [ -f "$out/$name.qsb" ] || { echo "missing: $name.qsb"; rc=1; }
    continue
  fi
  [ -n "$qsb" ] || { echo "qsb not found (install qt6-shadertools)" >&2; exit 2; }
  "$qsb" --qt6 -o "$out/$name.qsb" "$f"
  echo "$sum" > "$src/$name.sha256"
  echo "baked $name"
done
exit $rc
