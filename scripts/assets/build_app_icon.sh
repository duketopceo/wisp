#!/bin/sh
# Render the hand-authored app icon sources into the hicolor theme tree
# (plan U9). Sizes below 64 use the separate small-size drawings in
# assets/icons/app/hint/; 64 and up render assets/icons/app/wisp.svg.
# Needs resvg; oxipng is used when present. Output is deterministic.
#
#   sh scripts/assets/build_app_icon.sh [OUT_DIR]   (default assets/icons/hicolor)
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
src="$root/assets/icons/app"
out="${1:-$root/assets/icons/hicolor}"
command -v resvg >/dev/null || { echo "build_app_icon: resvg not found" >&2; exit 1; }

mkdir -p "$out/scalable/apps"
cp "$src/wisp.svg" "$out/scalable/apps/wisp.svg"
for n in 16 24 32 48 64 128 256 512; do
  dir="$out/${n}x${n}/apps"
  mkdir -p "$dir"
  if [ -f "$src/hint/$n.svg" ]; then in="$src/hint/$n.svg"; else in="$src/wisp.svg"; fi
  resvg -w "$n" -h "$n" "$in" "$dir/wisp.png"
  if command -v oxipng >/dev/null; then oxipng -q --strip all "$dir/wisp.png"; fi
done
echo "wrote $out"
