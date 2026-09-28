"""Desktop tools: app launch/focus/close and Hyprland workspace ops."""
import json
import shutil
import subprocess

from .. import config
from ..pipeline import hypr_env


def _resolve_apps(cfg: dict, harness: dict | None) -> dict:
    apps = dict(cfg.get("apps", {}))
    if harness:
        apps.update({n: a["launch"] for n, a in harness.get("apps", {}).items()
                     if a.get("launch")})
    return apps


def _exec_detached(binname: str) -> None:
    # Hyprland 0.56: hyprctl dispatch exec <cmd> hits a Lua parse bug
    # (hyprwm/Hyprland#16224); the working path is the Lua dispatcher.
    r = subprocess.run(["hyprctl", "eval", f'hl.dsp.exec_cmd("{binname}")'],
                       capture_output=True, text=True, env=hypr_env())
    if r.returncode != 0 or "ok" not in r.stdout:
        subprocess.run(["hyprctl", "dispatch", "exec", binname],
                       capture_output=True, env=hypr_env())


def launch(app: str, cfg: dict, harness: dict | None = None) -> str:
    apps = _resolve_apps(cfg, harness)
    binname = apps.get(app)
    if not binname:
        return f"SKIP (unknown app {app!r})"
    binary = binname.split()[0]
    if not (shutil.which(binary)
            or (config.HOME / ".local" / "bin" / binary).exists()):
        return f"SKIP ({app} -> {binary!r} not installed)"
    _exec_detached(binname)
    return f"LAUNCHED {app} -> {binname}"


def _dsp(lua: str, *fallback: str) -> subprocess.CompletedProcess:
    """Run a Hyprland Lua dispatcher (hl.dsp.*); `hyprctl dispatch`
    itself is broken by a Lua parse bug on 0.56+ (hyprwm/Hyprland#16224),
    so the dispatcher table must go through eval + hl.dispatch."""
    r = subprocess.run(["hyprctl", "eval", f"hl.dispatch({lua})"],
                       capture_output=True, text=True, env=hypr_env())
    if r.returncode == 0 and "ok" in (r.stdout if isinstance(r.stdout, str) else ""):
        return r
    if fallback:
        return subprocess.run(["hyprctl", "dispatch", *fallback],
                              capture_output=True, text=True,
                              env=hypr_env())
    return r


def focus(classname: str) -> str:
    r = _dsp(f'hl.dsp.focus({{window="class:^{classname}"}})',
             "focuswindow", f"class:^{classname}")
    if r.returncode == 0 and "ok" in r.stdout:
        return f"FOCUSED {classname}"
    return f"SKIP (no window matching class {classname!r})"


def close(classname: str) -> str:
    if classname:
        lua = f'hl.dsp.window.close({{window="class:^{classname}"}})'
        fb = ("closewindow", f"class:^{classname}")
    else:
        lua = "hl.dsp.window.close()"
        fb = ("killactive",)
    r = _dsp(lua, *fb)
    if r.returncode == 0 and "ok" in r.stdout:
        return f"CLOSED {classname or 'active window'}"
    return f"SKIP (nothing closed for {classname!r})"


def workspace(n: str) -> str:
    try:
        num = int(str(n).strip())
    except ValueError:
        return f"SKIP (workspace {n!r} not a number)"
    _dsp(f'hl.dsp.focus({{workspace={num}}})', "workspace", str(num))
    return f"WORKSPACE {num}"


def clients() -> list:
    r = subprocess.run(["hyprctl", "clients", "-j"],
                       capture_output=True, text=True, env=hypr_env())
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
