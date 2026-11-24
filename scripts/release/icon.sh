#!/usr/bin/env bash
# macOS app icon (U5): 1024×1024 source → .icns via iconutil (Apple's tool).
# Apple's current app-icon spec is square, layered artwork; the system applies
# the rounded-rectangle mask (see Apple HIG App Icons).
set -euo pipefail

SRC="${SRC:-assets/icons/hicolor/scalable/apps/wisp.svg}"
MASTER="${MASTER:-build/wisp-icon-1024.png}"
ICONSET="${ICONSET:-build/wisp.iconset}"
OUT="${OUT:-build/Wisp.app/Contents/Resources/wisp.icns}"

[ -f "$SRC" ] || { echo "icon source missing: $SRC" >&2; exit 1; }
command -v sips >/dev/null || { echo "sips missing (needs macOS)" >&2; exit 1; }
command -v iconutil >/dev/null || { echo "iconutil missing (needs macOS)" >&2; exit 1; }

mkdir -p "$(dirname "$MASTER")" "$(dirname "$OUT")"
rm -rf "$ICONSET"
# master must be 1024×1024, not 960: Apple requires the current square shape.
cp "$SRC" build/wisp-icon-1024.svg
sips -s format png --resampleWidth 1024 --resampleHeight 1024 \
    build/wisp-icon-1024.svg --out "$MASTER" >/dev/null
mkdir -p "$ICONSET"
for size in 16 32 48 64 128 256 512; do
  sips -s format png --resampleWidth "$size" --resampleHeight "$size" \
      "$MASTER" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
done
iconutil -c icns -o "$OUT" "$ICONSET"
echo "icon: $OUT"
