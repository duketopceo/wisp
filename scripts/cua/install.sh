#!/usr/bin/env bash
# Install the pinned cua-driver for wisp (user scope, no sudo, idempotent).
#
#   scripts/cua/install.sh [--dry-run]
#
# Reads scripts/cua/PIN (override: CUA_PIN_FILE), downloads the pinned
# release for this architecture, verifies its sha256, and only then places
# it at ~/.local/share/cua-driver/cua-driver. Writes the systemd --user
# unit from scripts/cua/cua-driver.service, then daemon-reload + enable
# --now. A checksum mismatch aborts before anything is written.
# --dry-run prints the plan and touches nothing (no network, no systemctl).
# Exit: 0 ok, 1 failure (incl. checksum), 2 usage.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIN_FILE="${CUA_PIN_FILE:-$HERE/PIN}"
UNIT_SRC="${CUA_UNIT_FILE:-$HERE/cua-driver.service}"
DEST_DIR="$HOME/.local/share/cua-driver"
BIN="$DEST_DIR/cua-driver"
LINK="$HOME/.local/bin/cua-driver"
UNIT_DST="$HOME/.config/systemd/user/cua-driver.service"

die() { echo "install.sh: $*" >&2; exit "${2:-1}"; }

DRY=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option '$a' (try --dry-run)" 2 ;;
  esac
done

[ -r "$PIN_FILE" ] || die "PIN file not found: $PIN_FILE"
[ -r "$UNIT_SRC" ] || die "unit template not found: $UNIT_SRC"

pin_get() { sed -n "s/^$1=//p" "$PIN_FILE" | head -n1; }
VERSION="$(pin_get CUA_VERSION)"
case "$(uname -m)" in
  aarch64|arm64) ARCH=AARCH64 ;;
  x86_64|amd64)  ARCH=X86_64 ;;
  *) die "unsupported architecture $(uname -m)" ;;
esac
URL="$(pin_get "CUA_URL_$ARCH")"
SHA="$(pin_get "CUA_SHA256_$ARCH")"
[ -n "$VERSION" ] || die "PIN has no CUA_VERSION"
[ -n "$URL" ] && [ -n "$SHA" ] || die "PIN has no URL/sha256 for $ARCH"
case "$SHA" in
  *[!0-9a-f]*) die "PIN sha256 for $ARCH is not 64 hex chars" ;;
esac
[ "${#SHA}" -eq 64 ] || die "PIN sha256 for $ARCH is not 64 hex chars"

sha_of() { sha256sum "$1" | cut -d' ' -f1; }
have_binary() { [ -f "$BIN" ] && [ "$(sha_of "$BIN")" = "$SHA" ]; }
unit_current() { [ -f "$UNIT_DST" ] && cmp -s "$UNIT_SRC" "$UNIT_DST"; }

if [ "$DRY" -eq 1 ]; then
  echo "cua-driver install plan (dry run, nothing is written):"
  echo "  version   $VERSION ($ARCH)"
  echo "  download  $URL"
  echo "  sha256    $SHA"
  if have_binary; then
    echo "  binary    $BIN already matches the pin: skip download"
  else
    echo "  binary    verify sha256, then place at $BIN"
  fi
  echo "  symlink   $LINK -> $BIN (if not present)"
  if unit_current; then
    echo "  unit      $UNIT_DST already current"
  else
    echo "  unit      write $UNIT_DST (from $UNIT_SRC)"
  fi
  echo "  systemd   systemctl --user daemon-reload; enable --now cua-driver.service"
  exit 0
fi

REPLACED=0
if have_binary; then
  echo "cua-driver $VERSION already installed at $BIN"
else
  command -v curl >/dev/null || die "curl is required"
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/cua-install.XXXXXX")"
  trap 'rm -rf "$tmp"' EXIT
  echo "downloading cua-driver $VERSION ($ARCH)"
  curl -fsSL --retry 2 -o "$tmp/cua-driver" "$URL" \
    || die "download failed: $URL"
  got="$(sha_of "$tmp/cua-driver")"
  if [ "$got" != "$SHA" ]; then
    die "checksum mismatch for $URL: expected $SHA, got $got; refusing to install"
  fi
  mkdir -p "$DEST_DIR"
  chmod 0755 "$tmp/cua-driver"
  [ -e "$BIN" ] && REPLACED=1
  mv -f "$tmp/cua-driver" "$BIN"
  echo "installed $BIN (sha256 verified)"
fi

mkdir -p "$(dirname "$LINK")"
if [ ! -e "$LINK" ] && [ ! -L "$LINK" ]; then
  ln -s "$BIN" "$LINK"
  echo "linked $LINK"
fi

CHANGED=0
if unit_current; then
  echo "unit already current: $UNIT_DST"
else
  mkdir -p "$(dirname "$UNIT_DST")"
  cp "$UNIT_SRC" "$UNIT_DST"
  CHANGED=1
  echo "wrote $UNIT_DST"
fi

if command -v systemctl >/dev/null; then
  [ "$CHANGED" -eq 1 ] && systemctl --user daemon-reload
  systemctl --user enable --now cua-driver.service
  # a replaced binary needs a restart to take effect
  [ "$REPLACED" -eq 1 ] && systemctl --user restart cua-driver.service
else
  echo "systemctl not found: start the service yourself" >&2
fi
echo "cua-driver $VERSION ready"
