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


def focus(classname: str) -> str:
    r = subprocess.run(
        ["hyprctl", "dispatch", "focuswindow", f"class:^{classname}"],
        capture_output=True, text=True, env=hypr_env())
    if r.returncode == 0 and "ok" in r.stdout:
        return f"FOCUSED {classname}"
    return f"SKIP (no window matching class {classname!r})"


def close(classname: str) -> str:
    target = f"class:^{classname}" if classname else ""
    if not target:
        r = subprocess.run(["hyprctl", "dispatch", "killactive"],
                           capture_output=True, text=True, env=hypr_env())
    else:
        r = subprocess.run(["hyprctl", "dispatch", "closewindow", target],
                           capture_output=True, text=True, env=hypr_env())
    if r.returncode == 0 and "ok" in r.stdout:
        return f"CLOSED {classname or 'active window'}"
    return f"SKIP (nothing closed for {classname!r})"


def workspace(n: str) -> str:
    try:
        num = int(str(n).strip())
    except ValueError:
        return f"SKIP (workspace {n!r} not a number)"
    subprocess.run(["hyprctl", "dispatch", "workspace", str(num)],
                   capture_output=True, env=hypr_env())
    return f"WORKSPACE {num}"


def clients() -> list:
    r = subprocess.run(["hyprctl", "clients", "-j"],
                       capture_output=True, text=True, env=hypr_env())
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
