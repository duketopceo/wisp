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
            ("quickshell", "the desktop companion"),
            ("ffmpeg", "audio resampling"),
            ("wpctl", "speaker ducking"),
            ("wl-copy", "clipboard delivery"),
            ("pw-play", "spoken audio playback"),
            ("notify-send", "desktop notifications"),
            ("espeak-ng", "fallback speech synthesis"),
            ("gh", "release attestation verification"),
            ("git", "repository installation and updates"),
            ("opencode", "background agents (optional)"),
            ("ollama", "local models (optional)"))
ALTERNATIVES = {"wtype": ("wtype", "ydotool"),
                "pw-play": ("pw-play", "paplay", "aplay"),
                "espeak-ng": ("espeak-ng", "espeak")}


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
    py = py or tuple(sys.version_info[:3])
    rows = []
    try:
        resolved_home = home.resolve(strict=True)
        safe_home = (home.is_absolute() and resolved_home != resolved_home.parent
                     and resolved_home.is_dir()
                     and os.access(resolved_home, os.W_OK | os.X_OK))
    except (OSError, RuntimeError):
        safe_home = False
    rows.append(_row("home", "ok" if safe_home else "block",
                     "user directory available" if safe_home else
                     "missing, inaccessible, relative or resolves to filesystem root",
                     "" if safe_home else "Run from your normal desktop terminal "
                     "with HOME set to your user directory."))
    rows.append(_row("os", "ok" if system == "Linux" else "block",
                     system, "" if system == "Linux"
                     else "Only Linux (Omarchy) is supported."))
    arch = ARCHES.get(machine)
    rows.append(_row("architecture", "ok" if arch else "block",
                     arch or machine or "unknown",
                     "" if arch else "No release is built for this machine."))
    rows.append(_row("python", "ok" if py >= (3, 11, 4) else "block",
                     ".".join(map(str, py)),
                     "" if py >= (3, 11, 4) else "Wisp needs Python 3.11.4+."))
    if disk_free is not None:
        free = disk_free()
    elif not safe_home:
        free = None
    else:
        try:
            free = shutil.disk_usage(home).free
        except OSError:
            free = None
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
                     "session environment present; bus access not probed"
                     if has_sd else
                     "systemctl/session environment missing; bus access not probed",
                     "" if has_sd else "Start wispd yourself, or log in "
                     "through a systemd user session."))
    missing_session = [name for name in ("XDG_RUNTIME_DIR", "WAYLAND_DISPLAY",
                                        "HYPRLAND_INSTANCE_SIGNATURE")
                       if not os.environ.get(name)]
    rows.append(_row("desktop session", "degraded" if missing_session else "ok",
                     ("missing " + ", ".join(missing_session) if missing_session
                      else "environment present") + "; live desktop access not probed",
                     "Run onboard/doctor from your normal desktop terminal. "
                     "A headless install is still allowed." if missing_session else ""))
    for name, why in OPTIONAL:
        found = None
        for candidate in ALTERNATIVES.get(name, (name,)):
            found = which(candidate)
            if found:
                break
        rows.append(_row(name, "ok" if found else "degraded",
                         found or f"not found; needed for {why}",
                         "" if found else
                         "Install separately if you need this capability."))
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


def render(rows, *, width: int = 80, color: bool = False,
           glyphs: bool = False) -> str:
    """The install/update preflight as a short report: `preflight:`, the
    problem rows (fail, then warn) one line each with `Try:` on its own
    line, and every passing check collapsed to one quiet line. A Try text
    shared by three or more rows is printed once at the end."""
    from .cli import output
    width = min(width, 100)
    word = {"ok": "ok", "degraded": "warn", "block": "fail"}
    tone = {"ok": "muted", "degraded": "warn", "block": "fail"}
    probs = sorted((r for r in rows if r["level"] != "ok"),
                   key=lambda r: r["level"] != "block")
    good = [r["id"] for r in rows if r["level"] == "ok"]
    counts = {}
    for r in probs:
        if r["fix"]:
            counts[r["fix"]] = counts.get(r["fix"], 0) + 1
    shared = [f for f, n in counts.items() if n >= 3]
    out = [output.heading("preflight:", color)]
    idw = min(16, max([len(r["id"]) for r in probs] or [0]))
    ind = " " * (2 + 4 + 1 + idw + 1)
    for r in probs:
        mark = output.paint(word[r["level"]], tone[r["level"]]) \
            if color else word[r["level"]]
        mark += " " * (4 - len(word[r["level"]]))
        head = f"  {mark} {r['id']:<{idw}} "
        out += output.wrap(r["detail"], width, ind, head)
        if r["fix"] and r["fix"] not in shared:
            out += output.wrap("Try: " + r["fix"], width, ind, ind)
    for f in shared:
        out += output.wrap("For the other warnings, try: " + f,
                           width, "  ", "  ")
    if good:
        body = output.wrap(", ".join(good), width, "       ", "  ok   ")
        out += [output.paint(l, "muted") if color else l for l in body]
    return "\n".join(out)


def refusal(rows) -> str:
    return ("Cannot continue; nothing was written.\n"
            + format_rows(blockers(rows)))
