#!/usr/bin/env bash
# macOS arm64 .dmg build + notarization (release tooling; docs/plans U3).
#
# Usage: scripts/release/dmg.sh build|verify|sha256
#   build  — DMG via create-dmg, sign inside-out (Developer ID Application,
#            hardened runtime + secure timestamp), notarytool --wait, staple.
#   verify — codesign --verify --deep --strict + stapler validate + SHA-256.
# Signing/notarization runs on the artifact only — a standalone CLI is not
# stapled (Apple SDK guidance). Requires Developer ID certs (App + Installer).
set -euo pipefail

APP_DIR="${APP_DIR:-build/Wisp.app}"
# The workflow sets RELEASE_TAG (top-level env); bump the default otherwise.
DMG_NAME="${DMG_NAME:-Wisp-${RELEASE_TAG:-1.0.0}.dmg}"
IDENTITY="${IDENTITY:-Developer ID Application}"

build() {
  [ -d "$APP_DIR" ] || { echo "app missing: $APP_DIR" >&2; exit 1; }
  command -v create-dmg >/dev/null || { echo "create-dmg missing" >&2; exit 1; }
  command -v codesign >/dev/null || { echo "codesign missing" >&2; exit 1; }
  command -v notarytool 2>/dev/null || command -v xcrun >/dev/null \
    || { echo "notarytool/xcrun missing" >&2; exit 1; }
  rm -f "$DMG_NAME"

  # Sign nested executables, libs and plugins inside out (no --deep on sign).
  find "$APP_DIR" -type f -perm -u+x \
       -exec codesign -s "$IDENTITY" --options runtime --timestamp {} +
  codesign -s "$IDENTITY" --options runtime --timestamp --force "$APP_DIR"

  create-dmg --volicon "$APP_DIR/Contents/Resources/wisp.icns" \
      --icon "Wisp.app" 100 150 --icon Applications 600 150 \
      "$DMG_NAME" "$APP_DIR" >/dev/null
  codesign -s "$IDENTITY" --options runtime --timestamp "$DMG_NAME"

  xcrun notarytool submit "$DMG_NAME" --wait
  xcrun stapler staple "$DMG_NAME"
  sha256
}

verify() {
  [ -e "$DMG_NAME" ] || { echo "dmg missing: $DMG_NAME" >&2; exit 1; }
  command -v codesign >/dev/null
  command -v stapler >/dev/null || command -v xcrun >/dev/null
  # Verification (not signing) may use --deep --strict.
  codesign --verify --deep --strict "$APP_DIR"
  xcrun stapler validate "$DMG_NAME"
}

sha256() {
  command -v shasum >/dev/null
  shasum -a 256 "$DMG_NAME"
}

case "${1:-}" in
  build) build ;;
  verify) verify ;;
  sha256) sha256 ;;
  *) echo "usage: $0 {build|verify|sha256}" >&2; exit 2 ;;
esac
