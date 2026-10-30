"""Pinned runtime installer (KTD8): download, verify, install ori and
OpenCode into `<data>/agent-runtime/<tool>/<version>/` behind a `current`
symlink. No sudo; nothing is written under the runtime root until the
SHA-256 matches the pin and the staged binary reports the pinned version.
Never runs ori's install.sh, `ori update` or `ori doctor --fix`.
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from typing import NamedTuple

from . import agent_pins
from .probes_cua import parse_version

FETCH_TIMEOUT_S = 120


class Result(NamedTuple):
    status: str          # installed | already | failed
    reason: str = ""


def fetch_url(url: str, dest) -> None:
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as r, \
            open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def version_of(binary) -> str | None:
    """`<binary> --version` -> semver, None when it can't be read. ori
    telemetry and update checks stay off."""
    env = agent_pins.ori_env()
    try:
        r = subprocess.run([str(binary), "--version"], capture_output=True,
                           text=True, timeout=5, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_version(r.stdout or r.stderr)


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_members(tar) -> list | None:
    """Regular files and dirs with relative, non-escaping names only;
    None when any member is absolute, has `..`, or is a link/device."""
    out = []
    for m in tar.getmembers():
        parts = pathlib.PurePosixPath(m.name).parts
        if m.name.startswith("/") or ".." in parts \
                or not (m.isreg() or m.isdir()):
            return None
        out.append(m)
    return out


def _stage_binary(tool, p, blob, stage) -> pathlib.Path | str:
    """Place the verified download as `stage/<tool>`; str = error."""
    dst = stage / tool
    if not p["archive"]:
        shutil.copyfile(blob, dst)
    else:
        x = stage / "x"
        x.mkdir()
        try:
            with tarfile.open(blob, "r:gz") as t:
                members = _safe_members(t)
                if members is None:
                    return (f"{tool} archive has absolute, '..' or link "
                            "members; refusing to install")
                if hasattr(tarfile, "data_filter"):
                    t.extractall(x, members, filter="data")
                else:
                    t.extractall(x, members)
        except (tarfile.TarError, OSError) as e:
            return f"{tool} archive unreadable: {e}"
        found = next((f for f in sorted(x.rglob(tool)) if f.is_file()), None)
        if found is None:
            return f"no {tool} executable in the archive"
        shutil.copyfile(found, dst)
    dst.chmod(0o755)
    return dst


def _flip_current(tooldir: pathlib.Path, version: str) -> None:
    tmp = tooldir / f".current-{os.getpid()}"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(version)
    os.replace(tmp, tooldir / "current")


def install(tool, arch=None, fetch=None, dest_root=None,
            pin_fn=agent_pins.pin, version_fn=version_of) -> Result:
    arch = arch or agent_pins.machine_arch()
    p = pin_fn(tool, arch)
    if p is None:
        return Result("failed", f"no build for {arch}")
    if agent_pins.is_placeholder(p["sha256"]):
        return Result("failed", f"{tool} pin is a placeholder, not a "
                      "checksum; refusing to install")
    root = agent_pins.runtime_root(dest_root)
    tooldir = root / tool
    vdir = tooldir / p["version"]
    cur = tooldir / "current" / tool
    if (vdir / tool).is_file() and cur.resolve() == (vdir / tool).resolve() \
            and version_fn(cur) == p["version"]:
        return Result("already")
    with tempfile.TemporaryDirectory(prefix="wisp-agent-") as td:
        blob = pathlib.Path(td) / "download"
        try:
            (fetch or fetch_url)(p["url"], blob)
        except Exception as e:
            return Result("failed", f"{tool} download failed: {e}")
        if _sha256(blob) != p["sha256"].lower():
            return Result("failed", f"{tool} download does not match its "
                          "pinned SHA-256; nothing installed")
        stage = pathlib.Path(td) / "stage"
        stage.mkdir()
        staged = _stage_binary(tool, p, blob, stage)
        if isinstance(staged, str):
            return Result("failed", staged)
        got = version_fn(staged)
        if got != p["version"]:
            return Result("failed", f"{tool} reports {got or 'no version'}"
                          f", expected {p['version']}")
        if tool == "opencode" and int(got.split(".")[0]) \
                != agent_pins.OPENCODE_MAJOR:
            return Result("failed", f"opencode {got} is not "
                          f"{agent_pins.OPENCODE_MAJOR}.x")
        try:
            tooldir.mkdir(parents=True, exist_ok=True)
            new = tooldir / f".new-{os.getpid()}"
            shutil.rmtree(new, ignore_errors=True)
            new.mkdir()
            shutil.copyfile(staged, new / tool)
            (new / tool).chmod(0o755)
            shutil.rmtree(vdir, ignore_errors=True)
            os.replace(new, vdir)
            _flip_current(tooldir, p["version"])
        except OSError as e:
            return Result("failed", f"{tool} install failed: {e}")
    return Result("installed")
