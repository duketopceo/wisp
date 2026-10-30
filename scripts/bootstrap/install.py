#!/usr/bin/env python3
"""Inspect this file before running. Stdlib only; no sudo, keys or services.

Trust root: official GitHub release over HTTPS, SHA-256 from that publisher
or an independently obtained --sha256. This is NOT signature verification.
"""
import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

REPO = "duketopceo/wisp"
API = f"https://api.github.com/repos/{REPO}/releases"
DOWNLOAD = f"https://github.com/{REPO}/releases/download/"
TAG = re.compile(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?")
LIMIT = 400 * 1024 * 1024


def fetch(url, limit=LIMIT):
    request = urllib.request.Request(url, headers={"User-Agent": "wisp-bootstrap"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Download exceeds the size limit.")
    return data


def release_url(asset, tag):
    url = asset.get("browser_download_url", "")
    if url != DOWNLOAD + tag + "/" + asset["name"]:
        raise ValueError("Asset URL is not in the selected official release.")
    return url


def extract(archive, destination):
    """Validate the complete member list before extracting regular files."""
    with tarfile.open(archive, mode="r:gz") as tf:
        members, names, total = tf.getmembers(), set(), 0
        if len(members) > 50000:
            raise ValueError("Too many archive members.")
        for m in members:
            parts = m.name.rstrip("/").split("/")
            if not parts or any(p in ("", ".", "..") for p in parts) \
                    or "\\" in m.name or any(ord(c) < 32 for c in m.name) \
                    or not (m.isfile() or m.isdir()) \
                    or any(p in (".git", ".env", "id_rsa", "id_ed25519")
                           or p.startswith(".env.") for p in parts):
                raise ValueError("Unsafe archive member.")
            if m.name in names or m.size < 0:
                raise ValueError("Duplicate or invalid archive member.")
            names.add(m.name)
            total += m.size
        if total > 1024 * 1024 * 1024:
            raise ValueError("Expanded archive exceeds the size limit.")
        tops = {pathlib.PurePosixPath(m.name).parts[0] for m in members}
        if len(tops) != 1:
            raise ValueError("Archive must have one top-level directory.")
        top = next(iter(tops))
        required = ("wispd", "wisp/__init__.py", "assets/desktop/wisp.desktop",
                    "scripts/units/wispd.service", "shell-plugin/manifest.json")
        regular = {m.name for m in members if m.isfile()}
        if any(top + "/" + p not in regular for p in required):
            raise ValueError("Incomplete Wisp release archive.")
        # A fresh private staging tree contains no symlinks.
        for m in members:
            target = destination / m.name
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(m) as src, target.open("xb") as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
                target.chmod(0o755 if m.mode & 0o111 else 0o644)
    return destination / top


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="exact vMAJOR.MINOR.PATCH[-prerelease] tag")
    parser.add_argument("--dry-run", action="store_true",
                        help="show URLs and actions; no network or writes")
    parser.add_argument("--inspect-source", action="store_true",
                        help="print this bootstrap source and exit")
    parser.add_argument("--yes", action="store_true",
                        help="consent to verified download and user-scope install")
    parser.add_argument("--from-plugin", action="store_true",
                        help="leave marketplace plugin files untouched")
    parser.add_argument("--sha256", help="independently obtained archive SHA-256")
    args, extra = parser.parse_known_args(argv)
    if extra:
        parser.error("Unsupported arguments; never pass credentials to bootstrap.")
    if args.inspect_source:
        print(pathlib.Path(__file__).read_text(), end="")
        return 0
    if args.version and not TAG.fullmatch(args.version):
        parser.error("--version must be an exact release tag")
    if args.sha256 and not re.fullmatch(r"[a-fA-F0-9]{64}", args.sha256):
        parser.error("--sha256 must be 64 hexadecimal characters")
    arch = {"x86_64": "x86_64", "aarch64": "aarch64"}.get(platform.machine().lower())
    if platform.system() != "Linux" or not arch:
        print("Only Linux x86_64/aarch64 is supported.")
        return 4
    endpoint = API + ("/tags/" + args.version if args.version else "/latest")
    print(f"Release metadata: {endpoint}")
    print(f"Asset: wisp-linux-{arch}.tar.gz")
    print("Verify publisher SHA-256 before safe extraction; preview installer, "
          "then install user-scoped files. No service start or restart.")
    if args.dry_run:
        print("Dry run: no network, writes or service actions.")
        return 0
    if os.geteuid() == 0 or os.environ.get("SUDO_USER"):
        print("Refusing root/sudo installation. Run as your normal desktop user.")
        return 4
    if sys.version_info < (3, 11, 4):
        print("Python 3.11.4+ is required.")
        return 4
    if not args.yes and (not sys.stdin.isatty()
                         or input("Download and install these user-scoped files? [y/N] ")
                         .strip().lower() not in ("y", "yes")):
        print("Not installed. Use --yes only after inspecting the plan/source.")
        return 2
    try:
        release = json.loads(fetch(endpoint, 4 * 1024 * 1024))
        tag = release["tag_name"]
        if not TAG.fullmatch(tag) or (args.version and tag != args.version):
            raise ValueError("Release tag does not match the selected version.")
        name = f"wisp-linux-{arch}.tar.gz"
        assets = {a["name"]: a for a in release.get("assets", [])}
        asset = assets[name]
        url = release_url(asset, tag)
        want = args.sha256
        trust = "independently supplied --sha256" if want else "publisher SHA-256"
        if not want and "SHA256SUMS" in assets:
            sums = fetch(release_url(assets["SHA256SUMS"], tag), 1024 * 1024).decode()
            hashes = [p[0] for ln in sums.splitlines()
                      if len(p := ln.split()) == 2 and p[1].lstrip("*") == name]
            if len(hashes) == 1:
                want = hashes[0]
        if not want:
            want = asset.get("digest", "").removeprefix("sha256:")
        if not want or not re.fullmatch(r"[a-fA-F0-9]{64}", want):
            raise ValueError("No valid release SHA-256 is available; refusing install.")
        blob = fetch(url)
        got = hashlib.sha256(blob).hexdigest()
        if got != want.lower():
            raise ValueError("Release SHA-256 mismatch; nothing installed.")
        print(f"Verified {tag}: {got} ({trust}); not a signature or attestation.")
        with tempfile.TemporaryDirectory(prefix="wisp-bootstrap-") as td:
            work = pathlib.Path(td)
            archive = work / name
            archive.write_bytes(blob)
            root = extract(archive, work / "tree")
            command = [sys.executable, str(root / "wispd"), "install"]
            if args.from_plugin:
                command.extend(["--from-plugin", "--yes"])
            # Preview is the same real installer and cannot mutate HOME.
            rc = subprocess.run(command + ["--dry-run"], cwd=root).returncode
            if rc:
                return rc
            rc = subprocess.run(command, cwd=root).returncode
            if rc:
                print("Installer failed; it may have written files. See docs/INSTALL.md.")
                return rc
        print("Installed; no daemon started or restarted. Next:\n"
              "  ~/.local/bin/wispd onboard --status\n"
              "  ~/.local/bin/wispd onboard\n"
              "  ~/.local/bin/wispd doctor\n"
              "Start services and test the microphone only when you choose.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"Bootstrap stopped: {detail}; no success claimed. "
              "Check the selected release and SHA-256. No service was started.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
