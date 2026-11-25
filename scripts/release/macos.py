#!/usr/bin/env python3
"""macOS arm64 packaging helpers (release tooling; see docs/plans U2).

`assert_arm64` is the deterministic, CI-safe core: it parses the output of
`lipo -info` (or `file` when lipo is absent) and rejects anything but
arm64, so a wrongly-archived payload fails the build, never a user.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXPECTED_ARCH = "arm64"


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True,
                          check=True).stdout


def assert_arm64(path: Path) -> str:
    """Return the arch name parsed from lipo/file output; raise if not arm64."""
    if shutil.which("lipo"):
        out = _run(["lipo", "-info", str(path)])
    else:
        out = _run(["file", str(path)])
    found = re.findall(r"\b(arm64|arm64e|x86_64|i386|universal)\b", out)
    arch = "arm64" if "arm64" in found or "arm64e" in found else ""
    if arch != EXPECTED_ARCH:
        raise ValueError(f"expected arm64 binary, got {arch!r} in {path}")
    return arch


def otool_check(path: Path) -> None:
    """A plain `otool -L` run must succeed on a linked arm64 artifact."""
    _run(["otool", "-L", str(path)])


def build(out_dir: Path, dist_dir: Path) -> Path:
    """Build wispd with PyInstaller, target-arch arm64, return the bundle dir."""
    entry = Path(__file__).resolve().parent.parent.parent / "wispd"
    if not entry.is_file():
        raise ValueError(f"wispd entry missing at {entry}")
    cmd = [sys.executable, "-m", "PyInstaller", "--target-arch",
           EXPECTED_ARCH, "-y", "--dist-dir", str(dist_dir),
           "--name", "wispd", str(entry)]
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    return dist_dir / "wispd"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build", action="store_true",
                   help="run PyInstaller (requires macOS) before asserting")
    p.add_argument("--check", type=Path, default=None,
                   help="assert a built artifact is arm64")
    args = p.parse_args()
    if args.build:
        out = build(Path("build"), Path("dist"))
        for f in out.rglob("*"):
            if f.is_file():
                print(f)
        args.check = out
    if args.check is None:
        p.error("pass --check PATH or --build")
    assert_arm64(args.check)
    print(f"arm64 OK: {args.check}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
