"""Platform seam — every OS-specific shell-out routes through here so
macOS (U7) / Windows (U8) / generic-Linux (U9) adapters land without
call-site edits. Commands are argv lists; the Linux table is
byte-for-byte what the code did before this seam existed.

Detection: ``sys.platform`` with a ``DIMD_OS`` override (mirrors the
Rust core) so adapters are unit-testable on any host.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()


def current() -> str:
    """'linux' | 'macos' | 'windows' (DIMD_OS wins — test/dev hook)."""
    o = os.environ.get("DIMD_OS", "")
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


def _ps(script: str) -> list:
    return ["powershell", "-NoProfile", "-NonInteractive",
            "-Command", script]


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
        base = HOME / "Library" / "Application Support" / "dim-agent"
        tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "dim-agent"
        return base, base, tmp
    if o == "windows":
        return (HOME / "AppData" / "Roaming" / "dim-agent",
                HOME / "AppData" / "Local" / "dim-agent",
                Path(os.environ.get("TEMP", "/tmp")) / "dim-agent")
    return (HOME / ".config" / "dim-agent",
            HOME / ".local" / "share" / "dim-agent",
            Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
            / "dim-agent")


# ── commands (argv) ─────────────────────────────────────────────────

def record_cmd(out: Path, seconds: float) -> list | None:
    """Mic capture → WAV at `out`. macOS: afrecord (brew sox
    fallback); None → caller reports 'no recorder found'."""
    o = current()
    if o == "linux":
        if _which("pw-record"):
            return ["pw-record", "--rate", "16000", "--channels", "1",
                    "--format", "s16", "--sample-count",
                    str(int(16000 * seconds)), str(out)]
        if _which("arecord"):
            return ["arecord", "-D", "default", "-r", "16000",
                    "-c", "1", "-f", "S16_LE", "-d", str(seconds),
                    str(out)]
        return None
    if o == "macos":
        if _which("afrecord"):
            return ["afrecord", "-f", "WAVE", "-d", str(seconds),
                    str(out)]
        if _which("sox"):
            return ["sox", "-d", "-r", "16000", "-c", "1", str(out),
                    "trim", "0", str(seconds)]
        return None
    if o == "windows":
        if _which("sox"):
            return ["sox", "-t", "waveaudio", "-d", "-r", "16000",
                    "-c", "1", str(out), "trim", "0", str(seconds)]
        return None
    return None


def sampler_cmd(seconds: float) -> list | None:
    """Live mic level: unsigned-8 PCM (200 Hz mono) on stdout.
    macOS: sox only; None → level stays 0."""
    o = current()
    if o == "linux":
        if _which("arecord"):
            return ["arecord", "-D", "default", "-f", "U8", "-r", "200",
                    "-c", "1", "-d", str(seconds)]
        return None
    if o == "macos":
        if _which("sox"):
            return ["sox", "-d", "-t", "u8", "-r", "200", "-c", "1",
                    "-", "trim", "0", str(seconds)]
        return None
    if o == "windows":
        if _which("sox"):
            return ["sox", "-t", "waveaudio", "-d", "-t", "u8",
                    "-r", "200", "-c", "1", "-",
                    "trim", "0", str(seconds)]
        return None
    return None


def screenshot_cmd(out: Path) -> list | None:
    o = current()
    if o == "linux":
        return ["grim", str(out)] if _which("grim") else None
    if o == "macos":
        return (["screencapture", "-x", str(out)]
                if _which("screencapture") else None)
    if o == "windows":
        if _which("powershell"):
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
        return ["wtype", "--", text] if _which("wtype") else None
    if o == "macos":
        return _osa_keystroke(text) if _which("osascript") else None
    if o == "windows":
        if _which("powershell"):
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
        if not _which("powershell"):
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
        if not _which("powershell"):
            return None
        e = lambda s: s.replace("'", "''")
        return _ps(
            "if (Get-Module -ListAvailable BurntToast) { "
            f"New-BurntToastNotification -Text '{e(title)}',"
            f"'{e(body)}' }} else {{ msg * '{e(title)}: {e(body)}' }}")
    return None


# ── window management ───────────────────────────────────────────────

def _hypr(*args: str) -> list:
    """hyprctl argv with HYPRLAND_INSTANCE_SIGNATURE env fix applied
    at spawn by callers via `_env()`."""
    return ["hyprctl", *args]


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


def _eval(lua: str) -> list:
    return _hypr("eval", f"hl.dispatch({lua})")


def wm_ok(p: subprocess.CompletedProcess) -> bool:
    """Did a wm command work? Linux: 'ok' in stdout (Hyprland eval
    convention) or clean exit for legacy dispatch; macOS: exit code."""
    if current() == "linux":
        out = p.stdout if isinstance(p.stdout, str) else ""
        return "ok" in out or p.returncode == 0
    return p.returncode == 0


def _try(cmds: list[list], timeout: int = 8) -> bool:
    """Run each argv until one satisfies wm_ok (fallback semantics —
    eval first, then legacy dispatch)."""
    for c in cmds:
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
        return [_eval(f'hl.dsp.focus({{window="class:^{cls}"}})'),
                _hypr("focuswindow", f"class:^{cls}")]
    if o == "macos":
        return [["open", "-a", cls]]
    if o == "windows":
        if _which("powershell"):
            return [_ps("(New-Object -ComObject WScript.Shell)"
                        f".AppActivate('{cls}') | Out-Null")]
        return []
    return []


def close_cmds(cls: str) -> list[list]:
    o = current()
    if o == "linux":
        if not cls:
            return [_eval("hl.dsp.window.close()"),
                    _hypr("killactive")]
        return [_eval(f'hl.dsp.window.close({{window="class:^{cls}"}})'),
                _hypr("closewindow", f"class:^{cls}")]
    if o == "macos":
        return [["osascript", "-e",
                 'tell application "System Events" to keystroke "w" '
                 'using command down']]
    if o == "windows":
        if not _which("powershell"):
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
        return [_eval(f"hl.dsp.focus({{workspace={n}}})"),
                _hypr("workspace", str(n))]
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
        return [_eval(f'hl.dsp.exec_cmd("{cmdline}")'),
                _hypr("dispatch", "exec", cmdline)]
    if o == "macos":
        return [["sh", "-c", cmdline]]
    if o == "windows":
        return [["cmd", "/c", "start", "", "/b", cmdline]]
    return []


def monitors() -> list[dict]:
    """[{x,y,width,height,scale}] logical rects for point mapping."""
    o = current()
    if o == "linux":
        try:
            p = subprocess.run(["hyprctl", "monitors", "-j"],
                               capture_output=True, text=True,
                               timeout=5, env=_env())
            import json
            return json.loads(p.stdout) if p.returncode == 0 else []
        except Exception:
            return []
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
        if not _which("powershell"):
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
    """Only Linux writes a Hyprland bind in `dimd install` — macOS
    hotkeys are a SKHD/native concern (see docs/MACOS.md)."""
    return current() == "linux"


def missing_deps_hint() -> str:
    return {"linux": "need grim/wtype/pw-record/espeak + Hyprland",
            "macos": "need screencapture/osascript/afrecord; grant "
                     "Screen Recording + Accessibility in System "
                     "Settings",
            "windows": "need powershell + sox (sox --waveaudio for mic); Accessibility n/a — toast via BurntToast optional"}[current()]
