"""One preflight for `wispd install`, `wispd update` and `wispd doctor`.

Each row is {id, level, detail, fix}. `block` stops a real install or
update before anything is written; `degraded` is reported and never
stops one (an optional capability, or no systemd to run the units);
`ok` is information. Nothing here reads a key, an `.env` file or any
user content, and nothing is written or started.
"""
import os
import platform as _plat
import shutil
import sys

from . import config, deploy

MIN_FREE = 200 * 1024 * 1024    # install tree, plus one backup of it
ARCHES = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64",
          "arm64": "aarch64"}
OPTIONAL = (("hyprctl", "the push-to-talk bind and pointer"),
            ("pw-record", "microphone capture"),
            ("wtype", "typing into other windows"),
            ("grim", "screen capture"),
            ("opencode", "background agents (optional)"),
            ("ollama", "local models (optional)"))


def _row(id_, level, detail, fix=""):
    return {"id": id_, "level": level, "detail": detail, "fix": fix}


def run(home=None, opt=None, *, system=None, machine=None, py=None, disk_free=None,
        which=shutil.which, systemd=None, record=None) -> list:
    """The rows for this machine. Every environment probe is a seam so
    tests run offline and identically anywhere."""
    home = home or config.HOME
    opt = opt or home / ".local" / "opt" / "wisp"
    system = system or _plat.system()
    machine = (machine or _plat.machine()).lower()
    py = py or tuple(sys.version_info[:2])
    rows = []
    rows.append(_row("os", "ok" if system == "Linux" else "block",
                     system, "" if system == "Linux"
                     else "Only Linux (Omarchy) is supported."))
    arch = ARCHES.get(machine)
    rows.append(_row("architecture", "ok" if arch else "block",
                     arch or machine or "unknown",
                     "" if arch else "No release is built for this machine."))
    rows.append(_row("python", "ok" if py >= (3, 11) else "block",
                     ".".join(map(str, py)),
                     "" if py >= (3, 11) else "Wisp needs Python 3.11.4+."))
    if disk_free is None:
        probe = home
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            free = shutil.disk_usage(probe).free
        except OSError:
            free = None
    else:
        free = disk_free()
    if free is None:
        rows.append(_row("disk space", "degraded", "could not be measured"))
    else:
        enough = free >= MIN_FREE
        rows.append(_row("disk space", "ok" if enough else "block",
                         f"{free // (1024 * 1024)} MiB free",
                         "" if enough else
                         f"Free at least {MIN_FREE // (1024 * 1024)} MiB "
                         "in your home directory."))
    has_sd = systemd() if systemd else bool(
        which("systemctl") and os.environ.get("XDG_RUNTIME_DIR"))
    rows.append(_row("systemd user", "ok" if has_sd else "degraded",
                     "available" if has_sd else
                     "not available: files install, units are not started",
                     "" if has_sd else "Start wispd yourself, or log in "
                     "through a systemd user session."))
    for name, why in OPTIONAL:
        found = which(name)
        rows.append(_row(name, "ok" if found else "degraded",
                         found or f"not found; needed for {why}"))
    rec = record if record is not None else deploy.read()
    rows.append(_row("current install", "ok",
                     (str(rec.get("ref") or str(rec.get("commit") or "")[:12]
                          or "unknown") if rec else "none")
                     + (f" in {opt}" if rec else "")))
    return rows


def blockers(rows) -> list:
    return [r for r in rows if r["level"] == "block"]


def format_rows(rows, *, only_problems: bool = False) -> str:
    mark = {"ok": "ok  ", "degraded": "warn", "block": "MISS"}
    out = []
    for r in rows:
        if only_problems and r["level"] == "ok":
            continue
        line = f"  {mark[r['level']]} {r['id']:<16} {r['detail']}"
        if r["fix"]:
            line += f"  (Try: {r['fix']})"
        out.append(line)
    return "\n".join(out)


def refusal(rows) -> str:
    return ("Cannot continue; nothing was written.\n"
            + format_rows(blockers(rows)))
