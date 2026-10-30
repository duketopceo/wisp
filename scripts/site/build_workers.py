#!/usr/bin/env python3
"""Assemble the Three.js homepage, /plain/ and reviewed bootstrap for Workers."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def build(out):
    out = Path(out).resolve()
    if ROOT.is_relative_to(out) or (
        out.is_relative_to(ROOT) and not out.is_relative_to(ROOT / "build")
    ):
        raise ValueError("output must be under build/ or outside repository sources")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/site/build_3d.py"), "--out", str(out)],
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/site/build.py"), "--out", str(out / "plain")],
        check=True,
    )
    shutil.copyfile(ROOT / "scripts/bootstrap/install.py", out / "install.py")
    shutil.copyfile(ROOT / "site-3d/_headers", out / "_headers")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "build/published"))
    args = parser.parse_args()
    try:
        out = build(args.out)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"workers site: {exc}\n")
    print(f"Workers assets built in {out}")


if __name__ == "__main__":
    main()
