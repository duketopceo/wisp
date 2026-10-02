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
    from .. import platform
    platform._try(platform.launch_exec_cmds(binname))


def _on_path(binary: str) -> bool:
    """Is this command's first token launchable?

    Linux values are bare binaries, so a PATH probe is the right test.
    macOS values are `open -a "<Name>"` and `open` is on PATH, so the
    same probe works. Windows values are cmdlines handed to
    `cmd /c start`, where the target is resolved by the shell rather
    than PATH — probing would reject every one of them."""
    from .. import platform
    if platform.current() == "windows":
        return True
    return bool(shutil.which(binary)
                or (config.HOME / ".local" / "bin" / binary).exists())


def launch(app: str, cfg: dict, harness: dict | None = None) -> str:
    apps = _resolve_apps(cfg, harness)
    binname = apps.get(app)
    if not binname:
        return f"SKIP (unknown app {app!r})"
    binary = binname.split()[0]
    if not _on_path(binary):
        # terminal: fall back to the desktop's configured default
        # (xdg-terminal-exec) — e.g. ghostty isn't packaged on Asahi
        if app == "terminal" and shutil.which("xdg-terminal-exec"):
            binname = binary = "xdg-terminal-exec"
        else:
            return f"SKIP ({app} -> {binary!r} not installed)"
    _exec_detached(binname)
    return f"LAUNCHED {app} -> {binname}"


def focus(classname: str) -> str:
    from .. import platform
    cmds = platform.focus_cmds(classname)
    if not cmds:
        return (f"SKIP (focus unsupported — "
                f"{platform.missing_deps_hint()})")
    if platform._try(cmds):
        return f"FOCUSED {classname}"
    return f"SKIP (no window matching class {classname!r})"


def close(classname: str) -> str:
    from .. import platform
    if platform._try(platform.close_cmds(classname)):
        return f"CLOSED {classname or 'active window'}"
    return f"SKIP (nothing closed for {classname!r})"


def workspace(n: str) -> str:
    from .. import platform
    try:
        num = int(str(n).strip())
    except ValueError:
        return f"SKIP (workspace {n!r} not a number)"
    cmds = platform.workspace_cmds(num)
    if not cmds:
        return (f"SKIP (workspace {num} unsupported — "
                f"{platform.missing_deps_hint()})")
    platform._try(cmds)
    return f"WORKSPACE {num}"


def clients() -> list:
    """Open windows, as Hyprland reports them. Hyprland-only: no other
    platform has an equivalent enumerator here, so return [] instead of
    raising FileNotFoundError on a host without hyprctl."""
    from .. import platform
    if platform.current() != "linux":
        return []
    r = subprocess.run(["hyprctl", "clients", "-j"],
                       capture_output=True, text=True, env=hypr_env())
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
