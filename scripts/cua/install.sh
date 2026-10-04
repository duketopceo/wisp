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

# sha256sum is GNU coreutils; macOS ships `shasum` (perl) instead.
if command -v sha256sum >/dev/null 2>&1; then
  sha_of() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null 2>&1; then
  sha_of() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
  die "need sha256sum or shasum to verify downloads"
fi
BIN_SHA="$(pin_get "CUA_BIN_SHA256_$ARCH")"
have_binary() {
  [ -x "$BIN" ] || return 1
  if [ -n "$BIN_SHA" ]; then
    [ "$(sha_of "$BIN")" = "$BIN_SHA" ]
  else
    "$BIN" --version 2>/dev/null | grep -qF "$VERSION"
  fi
}
unit_current() { [ -f "$UNIT_DST" ] && cmp -s "$UNIT_SRC" "$UNIT_DST"; }

# Refuse archives with absolute paths, `..` members or links.
check_members() {
  local names kinds
  names="$(tar -tzf "$1")" || return 1
  if printf '%s\n' "$names" | grep -Eq '^/|(^|/)\.\.(/|$)'; then
    return 1
  fi
  kinds="$(tar -tzvf "$1" | cut -c1)" || return 1
  if printf '%s\n' "$kinds" | grep -Eq '^[lh]'; then
    return 1
  fi
}

if [ "$DRY" -eq 1 ]; then
  echo "cua-driver install plan (dry run, nothing is written):"
  echo "  version   $VERSION ($ARCH)"
  echo "  download  $URL"
  echo "  sha256    $SHA (archive)"
  if have_binary; then
    echo "  binary    $BIN already matches the pin: skip download"
  else
    echo "  binary    verify archive sha256, extract (no absolute/.. members),"
    echo "            copy the archive contents into $DEST_DIR"
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
  command -v tar >/dev/null || die "tar is required"
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/cua-install.XXXXXX")"
  trap 'rm -rf "$tmp"' EXIT
  echo "downloading cua-driver $VERSION ($ARCH)"
  curl -fsSL --retry 2 -o "$tmp/archive.tar.gz" "$URL" \
    || die "download failed: $URL"
  got="$(sha_of "$tmp/archive.tar.gz")"
  if [ "$got" != "$SHA" ]; then
    die "checksum mismatch for $URL: expected $SHA, got $got; refusing to install"
  fi
  check_members "$tmp/archive.tar.gz" \
    || die "archive has absolute paths, '..' members or links; refusing to install"
  mkdir "$tmp/x"
  tar -xzf "$tmp/archive.tar.gz" -C "$tmp/x" --no-same-owner \
    || die "extract failed"
  found="$(find "$tmp/x" -type f -name cua-driver | head -n1)"
  [ -n "$found" ] || die "no cua-driver executable in the archive"
  root="$(dirname "$found")"
  if [ -n "$BIN_SHA" ] && [ "$(sha_of "$found")" != "$BIN_SHA" ]; then
    die "extracted cua-driver does not match CUA_BIN_SHA256_$ARCH; refusing to install"
  fi
  [ -e "$BIN" ] && REPLACED=1
  mkdir -p "$DEST_DIR"
  chmod 0755 "$found"
  cp -a "$root/." "$DEST_DIR/"
  echo "installed $DEST_DIR (archive sha256 verified)"
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
