#!/usr/bin/env python3
"""Inspect this file before running. Stdlib only; no sudo, keys or services.

Payload trust: independently installed GitHub CLI and its Sigstore trust
roots verify keyless release-workflow attestations before extraction.
Publisher SHA-256 is integrity only; it never substitutes for authentication.
"""
import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
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
VERIFY_FLAGS = ("--bundle", "--repo", "--cert-identity", "--cert-oidc-issuer",
                "--source-ref", "--source-digest", "--signer-digest",
                "--deny-self-hosted-runners", "--digest-alg")


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


def verify_attestation(verifier, archive, bundle, tag, commit, work, trusted_root=None):
    """Use independently installed verifier/roots, never trust release roots."""
    env = dict(os.environ)
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN",
                 "GITHUB_ENTERPRISE_TOKEN"):
        env.pop(name, None)
    home = work / "verifier-home"
    home.mkdir(mode=0o700)
    env.update(HOME=str(home), GH_CONFIG_DIR=str(home / "config"),
               XDG_CONFIG_HOME=str(home / "config"),
               XDG_CACHE_HOME=str(home / "cache"), GH_HOST="github.com",
               GH_PROMPT_DISABLED="1")
    help_result = subprocess.run([verifier, "attestation", "verify", "--help"],
                                 env=env, capture_output=True, text=True,
                                 timeout=15)
    required = VERIFY_FLAGS + (("--custom-trusted-root",) if trusted_root else ())
    if help_result.returncode or any(flag not in help_result.stdout.split()
                                     for flag in required):
        raise ValueError("Installed gh lacks required attestation-verification "
                         "flags. Independently upgrade it or review source.")
    identity = f"https://github.com/{REPO}/.github/workflows/release.yml@refs/tags/{tag}"
    command = [verifier, "attestation", "verify", str(archive),
               "--bundle", str(bundle), "--repo", REPO,
               "--cert-identity", identity, "--cert-oidc-issuer",
               "https://token.actions.githubusercontent.com",
               "--source-ref", f"refs/tags/{tag}", "--source-digest", commit,
               "--signer-digest", commit, "--deny-self-hosted-runners",
               "--digest-alg", "sha256"]
    if trusted_root:
        command.extend(["--custom-trusted-root", str(trusted_root)])
    checked = subprocess.run(command, env=env, capture_output=True,
                             text=True, timeout=120)
    if checked.returncode:
        raise ValueError("Keyless attestation verification failed; no extraction "
                         "or payload execution is permitted.")


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
    parser.add_argument("--trusted-root",
                        help="independently provisioned gh/Sigstore trusted-root JSON; never a release asset")
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
    print("Require independent gh/Sigstore attestation verification plus SHA-256 "
          "before safe extraction; preview installer, "
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
    home = pathlib.Path(os.environ.get("HOME", ""))
    try:
        resolved_home = home.resolve(strict=True)
        safe_home = (home.is_absolute() and resolved_home != resolved_home.parent
                     and resolved_home.is_dir())
    except (OSError, RuntimeError):
        safe_home = False
    if not safe_home:
        print("Refusing installation: HOME must be an existing, accessible absolute "
              "directory that does not resolve to /. "
              "Run from your normal desktop terminal. "
              "Nothing was written.")
        return 4
    if not args.yes and (not sys.stdin.isatty()
                         or input("Download and install these user-scoped files? [y/N] ")
                         .strip().lower() not in ("y", "yes")):
        print("Not installed. Use --yes only after inspecting the plan/source.")
        return 2
    verifier = shutil.which("gh")
    if not verifier:
        print("Refusing payload execution: independently install GitHub CLI "
              "with artifact-attestation verification, or review/build the "
              "source manually. No checksum-only fallback.")
        return 4
    try:
        trusted_root = pathlib.Path(args.trusted_root).resolve() if args.trusted_root else None
        if trusted_root and not trusted_root.is_file():
            raise ValueError("Independent trusted-root file is missing; "
                             "no release-provided root will be accepted.")
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
        bundle_asset = assets.get(name + ".sigstore.json")
        if not bundle_asset:
            raise ValueError("Required public keyless attestation bundle is missing.")
        commit = json.loads(fetch(
            f"https://api.github.com/repos/{REPO}/commits/{tag}",
            4 * 1024 * 1024))["sha"]
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("Cannot establish the exact release-tag source digest.")
        blob = fetch(url)
        got = hashlib.sha256(blob).hexdigest()
        if got != want.lower():
            raise ValueError("Release SHA-256 mismatch; nothing installed.")
        print(f"Integrity checked {tag}: {got} ({trust}); authentication pending.")
        with tempfile.TemporaryDirectory(prefix="wisp-bootstrap-") as td:
            work = pathlib.Path(td)
            archive = work / name
            archive.write_bytes(blob)
            bundle = work / (name + ".sigstore.json")
            bundle.write_bytes(fetch(release_url(bundle_asset, tag),
                                     16 * 1024 * 1024))
            verify_attestation(verifier, archive, bundle, tag, commit, work, trusted_root)
            print(f"Keyless attestation verified for release.yml at "
                  f"refs/tags/{tag}, source {commit}.")
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
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError,
            subprocess.TimeoutExpired) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"Bootstrap stopped: {detail}; no success claimed. "
              "Check the selected release and SHA-256. No service was started.")
        print("No checksum-only downgrade. Independently install/repair gh and "
              "its trusted roots, or inspect and build the source manually.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
