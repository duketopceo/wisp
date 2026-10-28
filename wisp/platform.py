"""Platform seam — every OS-specific shell-out routes through here.
Commands are argv lists. Wisp is Linux-only (Hyprland/Omarchy);
`current()` stays as a constant shim so callers and tests that patch
it keep working.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import hypr

HOME = Path.home()


def current() -> str:
    """Always 'linux' — Wisp supports Linux only."""
    return "linux"


def _which(b: str) -> bool:
    return shutil.which(b) is not None


def resolve_exe(argv0):
    """Pass-through (kept for existing callers)."""
    return argv0


def desktop() -> str:
    """Linux compositor: 'hyprland'|'gnome'|'kde'|'x11'|'unknown'.
    `WISP_DESKTOP` env override mirrors the Rust core (tests,
    forced fallbacks)."""
    d = os.environ.get("WISP_DESKTOP", "")
    if d in ("hyprland", "gnome", "kde", "x11"):
        return d
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or _which("hyprctl"):
        return "hyprland"
    cur = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gnome" in cur:
        return "gnome"
    if "kde" in cur or "plasma" in cur:
        return "kde"
    if os.environ.get("DISPLAY") and not os.environ.get(
            "WAYLAND_DISPLAY"):
        return "x11"
    return "unknown"


# ── runtime dirs ────────────────────────────────────────────────────

def dirs() -> tuple[Path, Path, Path]:
    """(config, data, runtime)."""
    return (HOME / ".config" / "wisp",
            HOME / ".local" / "share" / "wisp",
            Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
            / "wisp")


# ── commands (argv) ─────────────────────────────────────────────────

def record_cmd(out: Path, seconds: float | None) -> list | None:
    """Mic capture → WAV at `out`. seconds=None → open-ended toggle
    capture (caller stops with SIGINT); with a value it self-terminates
    after that many seconds. None →
    caller reports 'no recorder found'."""
    if _which("pw-record"):
        cmd = ["pw-record", "--rate", "16000", "--channels", "1",
               "--format", "s16"]
        if seconds:
            cmd += ["--sample-count", str(int(16000 * seconds))]
        return cmd + [str(out)]
    if _which("arecord"):
        cmd = ["arecord", "-D", "default", "-r", "16000",
               "-c", "1", "-f", "S16_LE"]
        if seconds:
            cmd += ["-d", str(seconds)]
        return cmd + [str(out)]
    return None


def stream_cmd() -> list | None:
    """Mic as raw 16 kHz mono s16 PCM on stdout (the wake word, B33)."""
    if _which("pw-record"):
        return ["pw-record", "--rate", "16000", "--channels", "1",
                "--format", "s16", "-"]
    if _which("arecord"):
        return ["arecord", "-D", "default", "-r", "16000", "-c", "1",
                "-f", "S16_LE", "-t", "raw"]
    return None


def sampler_cmd(seconds: float | None) -> list | None:
    """Live mic level: unsigned-8 PCM (200 Hz mono) on stdout.
    seconds=None → unbounded (toggle mode; caller kills the proc).
    None → level stays 0."""
    if _which("arecord"):
        cmd = ["arecord", "-D", "default", "-f", "U8", "-r", "200",
               "-c", "1"]
        if seconds:
            cmd += ["-d", str(seconds)]
        return cmd
    return None


def screenshot_cmd(out: Path, output: str | None = None) -> list | None:
    dt = desktop()
    order = {
        "hyprland": ["grim", "gnome-screenshot", "spectacle",
                     "maim"],
        "gnome": ["gnome-screenshot", "spectacle", "grim", "maim"],
        "kde": ["spectacle", "grim", "gnome-screenshot", "maim"],
        "x11": ["maim", "grim"],
    }.get(dt, ["grim", "gnome-screenshot", "spectacle", "maim"])
    for b in order:
        if _which(b):
            if b == "gnome-screenshot":
                return [b, "-f", str(out)]
            if b == "spectacle":
                return [b, "-b", "-n", "-o", str(out)]
            cmd = [b, str(out)]
            # grim captures every output; `-o` limits to one —
            # needed for headless/virtual outputs and panels whose
            # screencopy stalls when powered off (lid closed).
            if output and b == "grim":
                cmd = [b, "-o", output, str(out)]
            return cmd
    return None


def window_screenshot_cmd(out: Path, geometry: tuple | None) -> list | None:
    """Capture only the focused window's rectangle (x, y, w, h), the
    retry for a blank full-screen frame. grim and maim can crop; the
    other tools cannot, so there is no window retry for them."""
    if not geometry or len(geometry) != 4:
        return None
    x, y, w, h = (int(v) for v in geometry)
    if w < 8 or h < 8:
        return None
    if _which("grim") and desktop() in ("hyprland", "gnome", "kde", ""):
        return ["grim", "-g", f"{x},{y} {w}x{h}", str(out)]
    if _which("maim"):
        return ["maim", "-g", f"{w}x{h}+{x}+{y}", str(out)]
    if _which("grim"):
        return ["grim", "-g", f"{x},{y} {w}x{h}", str(out)]
    return None


def active_geometry() -> tuple | None:
    """Focused window rectangle (x, y, w, h) in layout pixels, or None."""
    try:
        w = hypr.query("activewindow")
    except hypr.HyprError:
        return None
    if not isinstance(w, dict):
        return None
    at, size = w.get("at"), w.get("size")
    try:
        return (int(at[0]), int(at[1]), int(size[0]), int(size[1]))
    except (TypeError, ValueError, IndexError):
        return None


def type_text_cmd(text: str) -> list | None:
    order = {"hyprland": ["wtype", "ydotool"],
             "x11": ["xdotool"],
             }.get(desktop(), ["ydotool", "wtype", "xdotool"])
    for b in order:
        if _which(b):
            if b == "wtype":
                return [b, "--", text]
            if b == "ydotool":
                return [b, "type", "--", text]
            return [b, "type", "--clearmodifiers", "--", text]
    return None


def tts_binary() -> str | None:
    for b in ("espeak-ng", "espeak"):
        if _which(b):
            return b
    return None


ESPEAK_WPM = 175   # espeak's own default speaking rate


def tts_argv(msg: str, speed: float = 1.0, voice: str = "") -> list | None:
    """Builtin TTS argv for `msg` — used when voice.cmd is empty.
    `speed` is a multiplier on espeak's default rate; 1.0 adds no flag.
    `voice` (an espeak voice such as `es` or `pt-br`) adds `-v`."""
    b = tts_binary()
    if not b:
        return None
    pre = [b, "-v", voice] if voice else [b]
    if abs(speed - 1.0) < 1e-9:
        return pre + [msg]
    return pre + ["-s", str(round(ESPEAK_WPM * speed)), msg]


def notify_cmd(title: str, body: str) -> list | None:
    return ["notify-send", title, body]


# ── window management ───────────────────────────────────────────────

def _env(extra: dict | None = None) -> dict:
    """Env for spawned cmds — discovers the Hyprland instance dir
    when HIS isn't exported (systemd-launched daemon case)."""
    e = dict(os.environ)
    if "HYPRLAND_INSTANCE_SIGNATURE" not in e:
        hypr = Path(e.get("XDG_RUNTIME_DIR", "/tmp")) / "hypr"
        if hypr.is_dir():
            kids = sorted(hypr.iterdir())
            if kids:
                e["HYPRLAND_INSTANCE_SIGNATURE"] = kids[0].name
    e.update(extra or {})
    return e


def wm_ok(p: subprocess.CompletedProcess) -> bool:
    """Did a wm command work? Linux: 'ok' in stdout (Hyprland eval
    convention) or clean exit for legacy dispatch."""
    out = p.stdout if isinstance(p.stdout, str) else ""
    return "ok" in out or p.returncode == 0


def uses_hypr() -> bool:
    """Window ops on this host go through the Hyprland socket."""
    return desktop() in ("hyprland", "unknown")


def _try(cmds: list, timeout: int = 8) -> bool:
    """Run each command until one succeeds. A `hypr.LuaCmd` goes over the
    Hyprland socket (no fork); anything else is an argv list."""
    for c in cmds:
        if isinstance(c, hypr.LuaCmd):
            if hypr.run_lua(c):
                return True
            continue
        try:
            p = subprocess.run(c, capture_output=True, text=True,
                               timeout=timeout, env=_env())
        except Exception:
            continue
        if wm_ok(p):
            return True
    return False


def focus_cmds(cls: str) -> list[list]:
    dt = desktop()
    if dt in ("hyprland", "unknown"):
        return [hypr.LuaCmd(hypr.focus_class(cls))]
    if dt == "kde":
        if _which("kdotool"):
            return [["sh", "-c",
                     f"kdotool search --name '{cls}' "
                     "windowactivate %@"]]
        if _which("wmctrl"):
            return [["wmctrl", "-a", cls]]
        return []
    if dt == "x11":
        return [["wmctrl", "-a", cls]] if _which("wmctrl") else []
    return []  # gnome wayland: no wm api


def close_cmds(cls: str) -> list[list]:
    dt = desktop()
    if dt in ("hyprland", "unknown"):
        return [hypr.LuaCmd(hypr.close_window(cls))]
    if dt in ("kde", "x11"):
        if not cls:
            return ([["xdotool", "getactivewindow", "windowclose"]]
                    if _which("xdotool") else [])
        return ([["wmctrl", "-c", cls]]
                if _which("wmctrl") else [])
    return []  # gnome wayland


def workspace_cmds(n: int) -> list[list]:
    dt = desktop()
    if dt in ("hyprland", "unknown"):
        return [hypr.LuaCmd(hypr.focus_workspace(n))]
    if dt == "kde":
        return ([["qdbus", "org.kde.KWin", "/KWin",
                  "setCurrentDesktop", str(n)]]
                if _which("qdbus") else [])
    if dt == "x11":
        return ([["wmctrl", "-s", str(n - 1)]]  # 0-based
                if _which("wmctrl") else [])
    return []  # gnome wayland: no api


def launch_exec_cmds(cmdline: str) -> list[list]:
    if desktop() in ("hyprland", "unknown"):
        return [hypr.LuaCmd(hypr.exec_cmd(cmdline))]
    return [["setsid", "sh", "-c", cmdline]]  # detached spawn


def monitors() -> list[dict]:
    """[{x,y,width,height,scale}] logical rects for point mapping."""
    dt = desktop()
    if dt in ("hyprland", "unknown"):
        try:
            return hypr.query("monitors")
        except hypr.HyprError:
            return []
    if dt in ("kde", "x11"):
        # xrandr `NAME connected ... WxH+X+Y` (scale assumed 1)
        if not _which("xrandr"):
            return []
        try:
            p = subprocess.run(["xrandr", "--query"],
                               capture_output=True, text=True,
                               timeout=5)
            mons = []
            for line in p.stdout.splitlines():
                if " connected" not in line:
                    continue
                for tok in line.split():
                    if "x" in tok and "+" in tok:
                        wh, _, xy = tok.partition("+")
                        w, _, h = wh.partition("x")
                        x, _, y = xy.partition("+")
                        try:
                            mons.append({
                                "x": int(x), "y": int(y),
                                "width": int(w),
                                "height": int(h), "scale": 1})
                        except ValueError:
                            pass
                        break
            return mons
        except Exception:
            return []
    return []  # gnome wayland: no cheap CLI


def supports_hotkey_install() -> bool:
    """Only Hyprland writes a bind in `wispd install` — GNOME/KDE use
    the XDG GlobalShortcuts portal (tray app, U10)."""
    return desktop() == "hyprland"


def missing_deps_hint() -> str:
    return ("need pw-record/arecord + espeak; wm ops need Hyprland "
            "(hyprctl), KDE (kdotool/qdbus/wmctrl) or X11 "
            "(wmctrl/xdotool); typing: wtype or ydotool; "
            "shots: grim/gnome-screenshot/spectacle/maim")


def active_window() -> dict:
    """Focused window as {"class","title"}; {} when unsupported/empty."""
    try:
        w = hypr.query("activewindow")
    except hypr.HyprError:
        return {}
    if not isinstance(w, dict):
        return {}
    return {"class": w.get("class", ""), "title": w.get("title", "")}


def _cua_live() -> bool:
    """cua-driver reachable. Linux: binary on PATH plus the daemon
    socket (Wayland backend enabled server-side via
    CUA_DRIVER_RS_ENABLE_WAYLAND)."""
    if not _which("cua-driver"):
        return False
    return os.path.exists(
        os.path.expanduser("~/.cache/cua-driver/cua-driver.sock"))


def pointer_backend(cfg: dict | None = None,
                    exclude: tuple = ()) -> str | None:
    """Pointer injector name ('cua'|'hyprcursor'|'ydotool'|'wlrctl') or
    None (guide mode). Thin shim over `wisp.pointer.Registry` (W8); the
    selection rules live there. Kept for the Rust parity tests."""
    from . import pointer
    b = pointer.Registry(cfg).select(exclude=exclude)
    return b.name if b else None


def pointer_cmds(x: int, y: int, backend: str,
                 click: bool = True) -> list:
    """Argv list moving the pointer to logical (x,y) and optionally
    clicking. Logical = Hyprland compositor coords."""
    if backend == "cua":
        import json as _json
        from . import cua as _c
        # raw `call` argv bypasses the Cua client — carry the session
        # label explicitly so these dispatches record under "wisp" too
        if click:
            return [["cua-driver", "call", "click",
                     _json.dumps({"x": x, "y": y,
                                  "coordinate_frame": "desktop",
                                  "scope": "desktop",
                                  "session": _c.SESSION})]]
        return [["cua-driver", "call", "move_cursor",
                 _json.dumps({"x": x, "y": y, "scope": "desktop",
                              "session": _c.SESSION})]]
    if backend == "hyprcursor":
        cmds = [["hyprctl", "dispatch",
                 f"hl.dsp.cursor.move({{x={x},y={y}}})"]]
        if click:
            cmds.append(["ydotool", "click", "0xC0"])
        return cmds
    if backend == "ydotool":
        cmds = [["ydotool", "mousemove", "--absolute",
                 "-x", str(x), "-y", str(y)]]
        if click:
            cmds.append(["ydotool", "click", "0xC0"])
        return cmds
    if backend == "wlrctl":
        cmds = [["wlrctl", "pointer", "move", str(x), str(y)]]
        if click:
            cmds.append(["wlrctl", "pointer", "click", "left"])
        return cmds
    return []
