#!/usr/bin/env python3
"""Verify a Linux archive, preview it and install only into a temporary HOME.

This is a trusted-code regression check, not a sandbox for hostile Python code.
No Rust binary, daemon, desktop command, model or real host service runs.
"""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile

from build import TARGETS, excluded

REQUIRED = {
    "wispd", "bin/wispd-rs", "wisp/__init__.py", "wisp/budgets.json",
    "wisp/skills_seed/self-checkup/SKILL.md",
    "wisp/skills_seed/apps/github/SKILL.md",
    "assets/desktop/wisp.desktop", "assets/icons/hicolor/scalable/apps/wisp.svg",
    "shell-plugin/manifest.json", "shell-plugin/shaders/wisp.frag.qsb",
    "shells/debug/WispService.qml", "shells/debug/components/Icon.qml",
    "scripts/units/wispd.service", "scripts/build_harness.py",
    "scripts/fetch_whisper.sh", "scripts/cua/PIN", "scripts/cua/install.sh",
    "scripts/cua/cua-driver.service", "CHANGELOG.md", "LICENSE",
    "scripts/bootstrap/install.py", "browser-extension/manifest.json",
    "browser-extension/background.js", "browser-extension/lib.js",
    "browser-extension/popup.js", "browser-extension/popup.html",
    "THIRD_PARTY_NOTICES.md", "release.json", "payload.json",
}
MAX_BYTES = 400 * 1024 * 1024

# Run the real extracted entrypoint, not an import from the checkout. -I/-B
# ignores user site/PYTHONPATH and bytecode; the hook is set before app imports.
PREVIEW = r"""
import os, pathlib, runpy, sys
root = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
home = pathlib.Path.home().resolve()
sys.path.insert(0, str(root))
def writable(path):
    return mode == "install" and not isinstance(path, int) and (
        pathlib.Path(path).resolve().is_relative_to(home))
def deny_effects(event, args):
    if event.startswith(("subprocess.", "socket.", "os.exec", "os.spawn",
                         "os.posix_spawn")) or event in {
        "os.system", "os.fork", "os.forkpty", "pty.spawn",
        "ctypes.dlopen",
    }:
        # OSError also lets optional git metadata probes degrade normally.
        raise OSError("release preview denied side effect: " + event)
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod",
                 "os.chown", "os.truncate", "os.utime"}:
        if not writable(args[0]):
            raise RuntimeError("release preview denied filesystem mutation")
    if event in {"os.rename", "os.link", "os.symlink"}:
        if not all(writable(p) for p in args[:2]):
            raise RuntimeError("release preview denied filesystem mutation")
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            if not writable(args[0]):
                raise RuntimeError("release preview denied file write")
sys.addaudithook(deny_effects)
sys.argv = [str(root / "wispd"), "install"]
if mode == "preview":
    sys.argv.append("--dry-run")
runpy.run_path(str(root / "wispd"), run_name="__main__")
"""


def extract_verified(args, dest):
    archive = pathlib.Path(args.archive)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != args.sha256.lower():
        raise ValueError("archive SHA-256 mismatch")
    prefix = f"wisp-{args.target}"
    with tarfile.open(archive) as tf:
        seen, total = set(), 0
        for member in tf.getmembers():
            path = pathlib.PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name \
                    or path.as_posix() != member.name:
                raise ValueError(f"unsafe archive member: {member.name}")
            if member.name in seen or not member.isfile():
                raise ValueError(f"duplicate or non-regular archive member: {member.name}")
            if len(path.parts) < 2 or path.parts[0] != prefix \
                    or excluded(pathlib.Path(*path.parts[1:])):
                raise ValueError(f"unexpected archive member: {member.name}")
            seen.add(member.name)
            total += member.size
            if total > MAX_BYTES:
                raise ValueError("expanded archive exceeds size limit")
        tf.extractall(dest, filter="data")
    root = dest / prefix
    files = {p.relative_to(root).as_posix(): p for p in root.rglob("*")
             if p.is_file()}
    if REQUIRED - files.keys():
        raise ValueError(f"missing runtime files: {sorted(REQUIRED - files.keys())}")
    meta = json.loads(files["release.json"].read_text())
    for key in ("version", "commit", "target"):
        if meta[key] != getattr(args, key):
            raise ValueError(f"release metadata {key} mismatch")
    payload = json.loads(files["payload.json"].read_text())
    if payload.get("schema") != 1 or meta.get("schema") != 1:
        raise ValueError("unsupported release metadata schema")
    inventory = payload["files"]
    if set(inventory) != files.keys() - {"payload.json"}:
        raise ValueError("payload inventory does not match extracted files")
    for name, expected in inventory.items():
        path = files[name]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"] \
                or path.stat().st_size != expected["size"] \
                or path.stat().st_mode & 0o777 != expected["mode"]:
            raise ValueError(f"payload inventory mismatch: {name}")
    if json.loads(files["shell-plugin/manifest.json"].read_text())["version"] \
            != args.version.removeprefix("v"):
        raise ValueError("plugin version does not match release")
    return root, meta, len(inventory)


def run_cli(root, home, mode):
    (home / ".config" / "wisp").mkdir(parents=True, exist_ok=True)
    # Avoid the CLI's default-config creation; this smoke is strictly read-only.
    (home / ".config" / "wisp" / "config.toml").write_text(
        '[local]\nenabled = "false"\n', encoding="utf-8")
    (home / "bin").mkdir(exist_ok=True)
    (home / "run").mkdir(mode=0o700, exist_ok=True)
    env = {
        "HOME": str(home), "PATH": str(home / "bin"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_RUNTIME_DIR": str(home / "run"),
        "WISP_OS": "linux", "PYTHONUTF8": "1", "NO_COLOR": "1",
    }
    result = subprocess.run([sys.executable, "-I", "-B", "-c", PREVIEW,
                             str(root), mode],
                            cwd=home, env=env, capture_output=True, text=True,
                            timeout=60)
    if result.returncode or (mode == "preview"
                            and "dry run: nothing written" not in result.stdout):
        raise ValueError(f"extracted CLI {mode} failed:\n"
                         f"{result.stdout}\n{result.stderr}")


def verify_install(root, home, metadata):
    """Check actual installed bytes/resources, not just the archive preview."""
    opt = home / ".local" / "opt" / "wisp"
    runtime_trees = ("wisp", "shells", "scripts", "assets", "bin")
    expected = {p.relative_to(root).as_posix(): p
                for tree in runtime_trees for p in (root / tree).rglob("*")
                if p.is_file()}
    for name in ("wispd", "CHANGELOG.md", "release.json",
                 "docs/baselines/latency-harness.json"):
        expected[name] = root / name
    missing = [name for name, source in expected.items()
               if not (opt / name).is_file()
               or (opt / name).read_bytes() != source.read_bytes()]
    if missing:
        raise ValueError("isolated install missing or changed runtime files: "
                         + ", ".join(sorted(missing)[:20])
                         + f" ({len(missing)} total)")
    deploy = json.loads((opt / "deploy.json").read_text())
    if deploy.get("ref") != metadata["version"] \
            or deploy.get("commit") != metadata["commit"]:
        raise ValueError("isolated install deploy version/commit mismatch")
    launcher = home / ".local" / "bin" / "wispd"
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise ValueError("isolated install missing executable ~/.local/bin/wispd")
    plugin = home / ".config" / "omarchy" / "plugins" / "io.github.duketopceo.wisp"
    for source in (root / "shell-plugin").rglob("*"):
        if source.is_file():
            target = plugin / source.relative_to(root / "shell-plugin")
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                raise ValueError("isolated install plugin payload mismatch")
    unit = home / ".config" / "systemd" / "user" / "wispd.service"
    if unit.read_bytes() != (root / "scripts/units/wispd.service").read_bytes():
        raise ValueError("isolated install daemon unit mismatch")
    desktop = home / ".local/share/applications/wisp.desktop"
    if not desktop.is_file() or "@WISPD@" in desktop.read_text():
        raise ValueError("isolated install desktop entry missing or unrendered")
    return len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("archive", "sha256", "version", "commit"):
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--target", choices=TARGETS, required=True)
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="wisp-release-check-") as tmp:
            work = pathlib.Path(tmp)
            root, metadata, count = extract_verified(args, work / "tree")
            home = work / "home"
            run_cli(root, home, "preview")
            run_cli(root, home, "install")
            installed_count = verify_install(root, home, metadata)
            print(json.dumps({
                **metadata, "files_verified": count, "install_dry_run": "passed",
                "isolated_install": "passed", "installed_version": metadata["version"],
                "installed_files_verified": installed_count,
                "network_and_processes": "denied", "rust_binary_executed": False,
                "desktop_and_voice_smoke": "not run",
            }, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, tarfile.TarError,
            subprocess.TimeoutExpired) as error:
        parser.exit(1, f"release verification: {error}\n")


if __name__ == "__main__":
    main()
