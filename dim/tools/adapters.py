"""Optional personalization adapters — plugins, never dependencies.

Each adapter exposes `apps()` (name -> launch cmd) and `context()` (a
short text block for Jev's decision state). The first adapter that
provides a non-empty catalog wins; the generic fallback always works on
a fresh install.
"""
import configparser
import json
import pathlib
import shutil

from .. import config

DESKTOP_DIRS = [
    pathlib.Path("/usr/share/applications"),
    config.HOME / ".local" / "share" / "applications",
]

# skip noise: settings panels, helpers, and system plumbing
_SKIP_PREFIXES = ("org.gnome.Settings", "org.kde.", "avahi", "bvi",
                  "cmake", "cups", "gcr-", "gnome-", "java-", "krb5",
                  "nm-", "octopi", "org.freedesktop", "qv4l2", "xdg-")


def dayflow_harness() -> dict | None:
    """Adapter A: harness.json mined from dayflow activity (local only).
    Returns None when dayflow isn't installed."""
    return config.load_harness()


def generic_catalog() -> dict:
    """Adapter B: always-on fallback — .desktop files + PATH binaries.
    Produces the same {name: {launch, cues}} shape the harness writes."""
    apps = {}
    for d in DESKTOP_DIRS:
        if not d.is_dir():
            continue
        for f in d.glob("*.desktop"):
            if f.stem.lower().startswith(_SKIP_PREFIXES):
                continue
            entry = _parse_desktop(f)
            if not entry:
                continue
            name, cmd = entry
            if name in apps or not shutil.which(cmd.split()[0]):
                continue
            apps[name] = {"launch": cmd,
                          "cues": f"the {name} application"}
    # PATH binaries the user clearly launches by name
    for b in ("ghostty", "kitty", "alacritty", "chromium", "firefox",
              "code", "nautilus", "spotify", "discord", "slack"):
        if shutil.which(b) and b not in apps:
            apps[b] = {"launch": b, "cues": f"the {b} application"}
    return apps


def _parse_desktop(f: pathlib.Path) -> tuple | None:
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(f, encoding="utf-8")
        e = cp["Desktop Entry"]
        if e.get("NoDisplay", "false").lower() == "true" \
                or e.get("Type") != "Application":
            return None
        name = e.get("Name", f.stem).strip()
        exec_ = e.get("Exec", "").split(" %")[0].strip()
        if not exec_:
            return None
        key = f.stem.lower().replace("org.gnome.", "").replace(".", "-")
        return key, exec_
    except (configparser.Error, KeyError):
        return None


def best_catalog() -> dict:
    """harness.json when present, else the generic .desktop/PATH catalog.
    Same return shape as harness['apps']."""
    h = dayflow_harness()
    if h and h.get("apps"):
        return h["apps"]
    return generic_catalog()


def context() -> str:
    """Enrichment text for Jev's decision state."""
    h = dayflow_harness()
    if h:
        return h.get("context", "")
    return ""
