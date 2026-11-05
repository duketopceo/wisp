"""Optional personalization adapters — plugins, never dependencies.

Each adapter exposes `apps()` (name -> launch cmd) and `context()` (a
short text block for Jev's decision state). The first adapter that
provides a non-empty catalog wins; the generic fallback always works on
a fresh install.
"""
import configparser
import pathlib
import shutil

from .. import config

# user entries shadow system entries (XDG_DATA_HOME precedes XDG_DATA_DIRS)
DESKTOP_DIRS = [
    config.HOME / ".local" / "share" / "applications",
    pathlib.Path("/usr/share/applications"),
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
    """Adapter B: always-on fallback — the host's installed apps.
    Produces the same {name: {launch, cues}} shape the harness writes."""
    return _linux_catalog()


def _linux_catalog() -> dict:
    """Linux: .desktop entries + PATH binaries the user launches by name."""
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
            if not shutil.which(cmd.split()[0]):
                continue
            entry_v = {"launch": cmd, "cues": f"the {name} application"}
            apps.setdefault(name, entry_v)
            # reverse-DNS stems (ai.storyteller.cadcraft) hide the name
            # people actually say — also key the last segment
            short = f.stem.lower().rsplit(".", 1)[-1]
            if short and short != name:
                apps.setdefault(short, entry_v)
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
