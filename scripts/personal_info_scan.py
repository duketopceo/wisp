#!/usr/bin/env python3
"""Scan a directory for personal-info denylist tokens.

The list comes from WISP_PERSONAL_DENYLIST_FILE when that variable is
set, otherwise from WISP_PERSONAL_DENYLIST (one token per line). A hit
prints ``path:line`` relative to the scan root and the process exits
non-zero. Denied tokens are never printed. With no list set, the scan
prints a skip notice and exits 0.
"""
import os
import pathlib
import sys

_SKIP = "personal-info scan skipped: no denylist set"


def _parse(text: str) -> list[str]:
    tokens = []
    for raw in text.splitlines():
        token = raw.strip()
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _fold_map(text: str) -> tuple[str, list[int]]:
    """Return (casefolded text, index of each folded char in the original).

    Neither a regex with IGNORECASE nor slicing by folded indexes is correct
    here: casefold expands (Straße -> strasse, U+0130 -> two code points), so
    IGNORECASE misses the expansion and folded offsets drift. Mapping every
    folded character back to its source index keeps both cases covered.
    """
    folded: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        piece = char.casefold()
        folded.append(piece)
        origin.extend([index] * len(piece))
    return "".join(folded), origin


def _redact(text: str, tokens: list[str]) -> str:
    """Replace tokens, matching case-insensitively including casefold
    expansions, and never printing the token."""
    out = text
    for token in tokens:
        if not token:
            continue
        needle = token.casefold()
        if not needle:
            continue
        while True:
            folded, origin = _fold_map(out)
            at = folded.find(needle)
            if at < 0:
                break
            start = origin[at]
            end = origin[at + len(needle) - 1] + 1
            out = out[:start] + "[redacted]" + out[end:]
    return out


def _load(redact_tokens: list[str]) -> tuple[str, list[str]]:
    """Return (mode, tokens). mode is skip, fail, or scan."""
    file_spec = (os.environ.get("WISP_PERSONAL_DENYLIST_FILE") or "").strip()
    if file_spec:
        path = pathlib.Path(file_spec).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            message = _redact(
                f"cannot read denylist file: {path}",
                sorted(redact_tokens, key=len, reverse=True))
            print(message, file=sys.stderr)
            return "fail", []
        return "scan", _parse(text)
    inline = os.environ.get("WISP_PERSONAL_DENYLIST")
    if inline is None or not inline.strip():
        print(_SKIP)
        return "skip", []
    return "scan", _parse(inline)


class _Incomplete(Exception):
    """A file or directory could not be read, so the scan is inconclusive."""


def _text(path: pathlib.Path) -> str | None:
    """Decoded text, or None when the file is deliberately skipped as binary.

    A read failure raises _Incomplete instead of returning None: reporting a
    clean scan for a file that was never read is a false negative on the one
    check meant to catch secrets."""
    try:
        with path.open("rb") as handle:
            chunk = handle.read(8192)
            if b"\x00" in chunk:
                return None
            rest = handle.read()
    except OSError as exc:
        raise _Incomplete(f"cannot read {path}: {exc.strerror}") from exc
    try:
        return (chunk + rest).decode("utf-8")
    except UnicodeError:
        return None


def _hits(root: pathlib.Path, tokens: list[str]) -> list[str]:
    needles = [token.casefold() for token in tokens if token]
    found = []
    if not needles:
        return found

    def on_error(exc: OSError) -> None:
        raise _Incomplete(f"cannot walk {exc.filename}: {exc.strerror}")

    for dirpath, _dirnames, filenames in os.walk(root, onerror=on_error):
        for name in filenames:
            if name == "LICENSE":
                continue
            path = pathlib.Path(dirpath) / name
            text = _text(path)
            if text is None:
                continue
            rel = path.relative_to(root).as_posix()
            for number, line in enumerate(text.splitlines(), 1):
                folded = line.casefold()
                if any(needle in folded for needle in needles):
                    found.append(f"{rel}:{number}")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: personal_info_scan.py ROOT", file=sys.stderr)
        return 2
    inline = _parse(os.environ.get("WISP_PERSONAL_DENYLIST") or "")
    mode, tokens = _load(inline)
    if mode == "skip":
        return 0
    if mode == "fail":
        return 2
    root = pathlib.Path(argv[1])
    redact_with = sorted(
        dict.fromkeys(inline + tokens), key=len, reverse=True)
    if not root.is_dir():
        print(_redact(f"scan root is not a directory: {root}", redact_with),
              file=sys.stderr)
        return 2
    try:
        hits = _hits(root, tokens)
    except _Incomplete as exc:
        print(_redact(f"scan incomplete: {exc}", redact_with), file=sys.stderr)
        return 2
    for hit in hits:
        print(_redact(hit, redact_with))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
