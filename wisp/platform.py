"""Platform seam — every OS-specific shell-out routes through here so
macOS (U7) / Windows (U8) / generic-Linux (U9) adapters land without
call-site edits. Commands are argv lists; the Linux table is
byte-for-byte what the code did before this seam existed.

Detection: ``sys.platform`` with a ``WISP_OS`` override (mirrors the
Rust core) so adapters are unit-testable on any host.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import hypr

HOME = Path.home()


def current() -> str:
    """'linux' | 'macos' | 'windows' (WISP_OS wins — test/dev hook)."""
    o = os.environ.get("WISP_OS", "")
    if o in ("macos", "darwin"):
        return "macos"
    if o == "windows":
        return "windows"
    if o == "linux":
        return "linux"
    return {"darwin": "macos", "win32": "windows"}.get(
        sys.platform, "linux")


def _which(b: str) -> bool:
    return shutil.which(b) is not None


def desktop() -> str:
    """Linux compositor: 'hyprland'|'gnome'|'kde'|'x11'|'unknown'.
    `WISP_DESKTOP` env override mirrors the Rust core (tests,
    forced fallbacks). Meaningless off-Linux → returns 'unknown'."""
    if current() != "linux":
        return "unknown"
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


def _ps(script: str) -> list:
    b = _ps_bin() or "powershell"
    return [b, "-NoProfile", "-NonInteractive",
            "-Command", script]


def _ps_bin() -> str | None:
    """Windows shell: inbox powershell.exe or cross-platform pwsh."""
    for b in ("powershell", "pwsh"):
        if _which(b):
            return b
    return None


def _sendkeys_escape(t: str) -> str:
    out = []
    for ch in t:
        if ch in "{}+^%~()[]":
            out.append("{" + ch + "}")
        else:
            out.append(ch)
    return "".join(out)


# ── runtime dirs ────────────────────────────────────────────────────

def dirs() -> tuple[Path, Path, Path]:
    """(config, data, runtime) — format/contents identical across
    OSes, only the roots move. macOS: ~/Library/Application Support +
    $TMPDIR socket dir."""
    o = current()
    if o == "macos":
        base = HOME / "Library" / "Application Support" / "wisp"
        tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "wisp"
        return base, base, tmp
    if o == "windows":
        return (HOME / "AppData" / "Roaming" / "wisp",
                HOME / "AppData" / "Local" / "wisp",
                Path(os.environ.get("TEMP", "/tmp")) / "wisp")
    return (HOME / ".config" / "wisp",
            HOME / ".local" / "share" / "wisp",
            Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
            / "wisp")


# ── commands (argv) ─────────────────────────────────────────────────

def record_cmd(out: Path, seconds: float | None) -> list | None:
    """Mic capture → WAV at `out`. seconds=None → open-ended toggle
    capture (caller stops with SIGINT); with a value it self-terminates
    after that many seconds. macOS: afrecord (brew sox fallback); None →
    caller reports 'no recorder found'."""
    o = current()
    if o == "linux":
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
    if o == "macos":
        if _which("afrecord"):
            cmd = ["afrecord", "-f", "WAVE"]
            if seconds:
                cmd += ["-d", str(seconds)]
            return cmd + [str(out)]
        if _which("sox"):
            cmd = ["sox", "-d", "-r", "16000", "-c", "1", str(out)]
            if seconds:
                cmd += ["trim", "0", str(seconds)]
            return cmd
        return None
    if o == "windows":
        if _which("sox"):
            cmd = ["sox", "-t", "waveaudio", "-d", "-r", "16000",
                   "-c", "1", str(out)]
            if seconds:
                cmd += ["trim", "0", str(seconds)]
            return cmd
        return None
    return None


def sampler_cmd(seconds: float | None) -> list | None:
    """Live mic level: unsigned-8 PCM (200 Hz mono) on stdout.
    seconds=None → unbounded (toggle mode; caller kills the proc).
    macOS: sox only; None → level stays 0."""
    o = current()
    if o == "linux":
        if _which("arecord"):
            cmd = ["arecord", "-D", "default", "-f", "U8", "-r", "200",
                   "-c", "1"]
            if seconds:
                cmd += ["-d", str(seconds)]
            return cmd
        return None
    if o == "macos":
        if _which("sox"):
            cmd = ["sox", "-d", "-t", "u8", "-r", "200", "-c", "1", "-"]
            if seconds:
                cmd += ["trim", "0", str(seconds)]
            return cmd
        return None
    if o == "windows":
        if _which("sox"):
            cmd = ["sox", "-t", "waveaudio", "-d", "-t", "u8",
                   "-r", "200", "-c", "1", "-"]
            if seconds:
                cmd += ["trim", "0", str(seconds)]
            return cmd
        return None
    return None


def screenshot_cmd(out: Path, output: str | None = None) -> list | None:
    o = current()
    if o == "linux":
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
    if o == "macos":
        return (["screencapture", "-x", str(out)]
                if _which("screencapture") else None)
    if o == "windows":
        if _ps_bin():
            return _ps(
                "Add-Type -AssemblyName System.Windows.Forms,"
                "System.Drawing; $b=[System.Windows.Forms."
                "SystemInformation]::VirtualScreen; "
                "$bmp=New-Object System.Drawing.Bitmap $b.Width,"
                "$b.Height; $g=[System.Drawing.Graphics]::FromImage"
                "($bmp); $g.CopyFromScreen($b.Left,$b.Top,0,0,"
                "$bmp.Size); $bmp.Save('{out}'); $g.Dispose(); "
                "$bmp.Dispose()".format(out=str(out).replace(
                    "'", "''")))
        return None
    return None


def _osa_keystroke(text: str) -> list:
    esc = text.replace("\\", "\\\\").replace('"', '\\"')
    return ["osascript", "-e",
            f'tell application "System Events" to keystroke "{esc}"']


def type_text_cmd(text: str) -> list | None:
    o = current()
    if o == "linux":
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
    if o == "macos":
        return _osa_keystroke(text) if _which("osascript") else None
    if o == "windows":
        if _ps_bin():
            return _ps(
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.SendKeys]::SendWait("
                f'"{_sendkeys_escape(text)}")')
        return None
    return None


def tts_binary() -> str | None:
    o = current()
    if o == "linux":
        for b in ("espeak-ng", "espeak"):
            if _which(b):
                return b
        return None
    if o == "macos":
        return "say" if _which("say") else None
    return None


def tts_argv(msg: str) -> list | None:
    """Builtin TTS argv for `msg` — used when voice.cmd is empty.
    Windows speaks via PowerShell SAPI."""
    if current() == "windows":
        if not _ps_bin():
            return None
        esc = msg.replace("'", "''")
        return _ps(
            "Add-Type -AssemblyName System.Speech; "
            "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
            f".Speak('{esc}')")
    b = tts_binary()
    return [b, msg] if b else None


def notify_cmd(title: str, body: str) -> list | None:
    o = current()
    if o == "linux":
        return ["notify-send", title, body]
    if o == "macos":
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e",
                f'display notification "{esc(body)}" with title '
                f'"{esc(title)}"']
    if o == "windows":
        if not _ps_bin():
            return None
        e = lambda s: s.replace("'", "''")
        return _ps(
            "if (Get-Module -ListAvailable BurntToast) { "
            f"New-BurntToastNotification -Text '{e(title)}',"
            f"'{e(body)}' }} else {{ msg * '{e(title)}: {e(body)}' }}")
    return None


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
    convention) or clean exit for legacy dispatch; macOS: exit code."""
    if current() == "linux":
        out = p.stdout if isinstance(p.stdout, str) else ""
        return "ok" in out or p.returncode == 0
    return p.returncode == 0


def uses_hypr() -> bool:
    """Window ops on this host go through the Hyprland socket."""
    return current() == "linux" and desktop() in ("hyprland", "unknown")


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
    o = current()
    if o == "linux":
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
    if o == "macos":
        return [["open", "-a", cls]]
    if o == "windows":
        if _ps_bin():
            return [_ps("(New-Object -ComObject WScript.Shell)"
                        f".AppActivate('{cls}') | Out-Null")]
        return []
    return []


def close_cmds(cls: str) -> list[list]:
    o = current()
    if o == "linux":
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
    if o == "macos":
        return [["osascript", "-e",
                 'tell application "System Events" to keystroke "w" '
                 'using command down']]
    if o == "windows":
        if not _ps_bin():
            return []
        if not cls:
            return [_ps("(New-Object -ComObject WScript.Shell)"
                        ".SendKeys('%{F4}')")]
        return [_ps(f"Get-Process -Name '{cls}' -ErrorAction "
                    "SilentlyContinue | ForEach-Object { "
                    "$_.CloseMainWindow() | Out-Null }")]
    return []


def workspace_cmds(n: int) -> list[list]:
    o = current()
    if o == "linux":
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
    if o == "macos":
        codes = [18, 19, 20, 21, 23, 22, 26, 28, 25]  # 1..=9 key codes
        if 1 <= n <= 9:
            return [["osascript", "-e",
                     'tell application "System Events" to key code '
                     f"{codes[n - 1]} using control down"]]
        return []
    return []


def launch_exec_cmds(cmdline: str) -> list[list]:
    o = current()
    if o == "linux":
        if desktop() in ("hyprland", "unknown"):
            return [hypr.LuaCmd(hypr.exec_cmd(cmdline))]
        return [["setsid", "sh", "-c", cmdline]]  # detached spawn
    if o == "macos":
        return [["sh", "-c", cmdline]]
    if o == "windows":
        return [["cmd", "/c", "start", "", "/b", cmdline]]
    return []


def monitors() -> list[dict]:
    """[{x,y,width,height,scale}] logical rects for point mapping."""
    o = current()
    if o == "linux":
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
    if o == "macos":
        # system_profiler: physical px; scale 2 inferred for Retina —
        # approximation (AX/NSScreen is the precise path; residual).
        try:
            import json
            p = subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True, text=True, timeout=8)
            v = json.loads(p.stdout) if p.returncode == 0 else {}
        except Exception:
            return []
        mons, x_off = [], 0
        for gpu in v.get("SPDisplaysDataType", []):
            for d in gpu.get("spdisplays_displays", []):
                res = str(d.get("spdisplays_resolution", "0 x 0"))
                try:
                    w, h = [float(x) for x in res.split("x")[:2]]
                except ValueError:
                    w = h = 0.0
                scale = 2.0 if "Yes" in str(
                    d.get("spdisplays_retina", "")) else 1.0
                mons.append({"x": x_off, "y": 0, "width": w,
                             "height": h, "scale": scale})
                x_off += int(w / scale)
        return mons
    if o == "windows":
        if not _ps_bin():
            return []
        try:
            import json
            p = subprocess.run(_ps(
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.Screen]::AllScreens | "
                "ForEach-Object { [PSCustomObject]@{ x=$_.Bounds.X; "
                "y=$_.Bounds.Y; width=$_.Bounds.Width; "
                "height=$_.Bounds.Height; scale=1 } } | "
                "ConvertTo-Json -Compress"),
                capture_output=True, text=True, timeout=8)
            v = json.loads(p.stdout) if p.returncode == 0 else []
        except Exception:
            return []
        return v if isinstance(v, list) else [v]  # single screen = obj
    return []


def supports_hotkey_install() -> bool:
    """Only Hyprland writes a bind in `wispd install` — GNOME/KDE use
    the XDG GlobalShortcuts portal (tray app, U10); macOS is SKHD."""
    return current() == "linux" and desktop() == "hyprland"


def missing_deps_hint() -> str:
    return {"linux": "need pw-record/arecord + espeak; wm ops need Hyprland "
                     "(hyprctl), KDE (kdotool/qdbus/wmctrl) or X11 "
                     "(wmctrl/xdotool); typing: wtype or ydotool; "
                     "shots: grim/gnome-screenshot/spectacle/maim",
            "macos": "need screencapture/osascript + sox for mic (brew "
                     "install sox — there is no afrecord on macOS); "
                     "grant Screen Recording + Accessibility in System "
                     "Settings",
            "windows": "need powershell + sox (sox --waveaudio for mic); Accessibility n/a — toast via BurntToast optional"}[current()]


def active_window() -> dict:
    """Focused window as {"class","title"}; {} when unsupported/empty."""
    o = current()
    if o == "linux":
        try:
            w = hypr.query("activewindow")
        except hypr.HyprError:
            return {}
        if not isinstance(w, dict):
            return {}
        return {"class": w.get("class", ""), "title": w.get("title", "")}
    if o == "macos":
        if not _which("osascript"):
            return {}
        script = (
            'tell application "System Events" to set appName to '
            'name of first process whose frontmost is true\n'
            'tell application "System Events" to tell (first process '
            'whose frontmost is true) to set winTitle to '
            'name of front window\n'
            'return appName & "\\n" & winTitle')
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0 or not r.stdout.strip():
            return {}
        cls, _, title = r.stdout.strip().partition("\n")
        return {"class": cls, "title": title}
    if o == "windows":
        ps = (
            'Add-Type @"\nusing System;\nusing System.Text;\n'
            'using System.Runtime.InteropServices;\n'
            'public class FG {\n'
            '  [DllImport("user32.dll")] public static extern IntPtr '
            'GetForegroundWindow();\n'
            '  [DllImport("user32.dll")] public static extern int '
            'GetWindowText(IntPtr h, StringBuilder s, int n);\n'
            '  [DllImport("user32.dll")] public static extern uint '
            'GetWindowThreadProcessId(IntPtr h, out uint p);\n'
            '}\n"@\n'
            '$h=[FG]::GetForegroundWindow()\n'
            '$sb=New-Object System.Text.StringBuilder 512\n'
            '[void][FG]::GetWindowText($h,$sb,512)\n'
            '$procId=0; [void][FG]::GetWindowThreadProcessId($h,[ref]$procId)\n'
            '$p=Get-Process -Id $procId -ErrorAction SilentlyContinue\n'
            '[PSCustomObject]@{class=($p.ProcessName);title=$sb.ToString()} '
            '| ConvertTo-Json -Compress')
        try:
            r = subprocess.run(_ps(ps), capture_output=True, text=True,
                               timeout=8)
            if r.returncode != 0 or not r.stdout.strip():
                return {}
            w = json.loads(r.stdout)
            return {"class": w.get("class") or "",
                    "title": w.get("title") or ""}
        except Exception:
            return {}
    return {}


def _cua_live() -> bool:
    """cua-driver daemon reachable on its socket (Wayland backend
    enabled server-side via CUA_DRIVER_RS_ENABLE_WAYLAND)."""
    import os
    return _which("cua-driver") and os.path.exists(
        os.path.expanduser("~/.cache/cua-driver/cua-driver.sock"))


def pointer_backend(cfg: dict | None = None,
                    exclude: tuple = ()) -> str | None:
    """Pointer injector: 'cua' | 'hyprcursor' | 'ydotool' | 'wlrctl'
    | None.

    [pointer] backend = "cua"|"hyprcursor"|"ydotool"|"wlrctl"|"none"|
    "auto" (default). cua routes clicks through cua-driver's background
    virtual pointer — compositor-exact coords on native Wayland without
    stealing the user's cursor or focus. hyprcursor positions via
    Hyprland's own dispatcher — exact logical coords, immune to the
    uinput-scale mismatch ydotool's absolute move shows on scaled
    outputs — and clicks via ydotool. auto prefers the live cua daemon,
    then hyprcursor on Hyprland; macOS/Windows injection isn't built —
    returns None so callers degrade to guide mode.
    """
    want = (cfg or {}).get("pointer", {}).get("backend", "auto")
    if exclude:
        # fallback lookup: first usable backend outside `exclude`,
        # in auto order, ignoring an explicit [pointer] backend pin
        if current() != "linux":
            return None
        if "hyprcursor" not in exclude and _which("hyprctl") \
                and _which("ydotool"):
            return "hyprcursor"
        return next((b for b in ("ydotool", "wlrctl")
                     if b not in exclude and _which(b)), None)
    if want == "cua":
        return "cua" if _cua_live() else None
    if want == "hyprcursor":
        return want if _which("hyprctl") and _which("ydotool") \
            else None
    if want in ("ydotool", "wlrctl"):
        return want if _which(want) else None
    if want == "none" or current() != "linux":
        return None
    if _cua_live():
        return "cua"
    if _which("hyprctl") and _which("ydotool"):
        return "hyprcursor"
    for b in ("ydotool", "wlrctl"):
        if _which(b):
            return b
    return None


def pointer_cmds(x: int, y: int, backend: str,
                 click: bool = True) -> list:
    """Argv list moving the pointer to logical (x,y) and optionally
    clicking. Logical = Hyprland compositor coords."""
    if backend == "cua":
        import json as _json
        if click:
            return [["cua-driver", "call", "click",
                     _json.dumps({"x": x, "y": y,
                                  "coordinate_frame": "desktop",
                                  "scope": "desktop"})]]
        return [["cua-driver", "call", "move_cursor",
                 _json.dumps({"x": x, "y": y, "scope": "desktop"})]]
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
