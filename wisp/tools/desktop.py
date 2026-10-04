"""Desktop tools: app launch/focus/close and Hyprland workspace ops."""
import re
import shutil

from .. import config
from .. import hypr


def _resolve_apps(cfg: dict, harness: dict | None) -> dict:
    apps = dict(cfg.get("apps", {}))
    if harness:
        apps.update({n: a["launch"] for n, a in harness.get("apps", {}).items()
                     if a.get("launch")})
    return apps


def _wm_down() -> str | None:
    """Tool-failure string when window ops need Hyprland and its socket
    is not answering (checked by the startup/periodic probe, no fork)."""
    from .. import platform
    if platform.uses_hypr() and not hypr.available():
        return "ERROR tool_failed (hypr_unavailable)"
    return None


def _exec_detached(binname: str) -> bool:
    from .. import platform
    return platform._try(platform.launch_exec_cmds(binname))


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


def _browseros_live() -> bool:
    """BrowserOS MCP server reachable → the signed-in agent browser is
    running, so 'browser' should mean it rather than a cold chromium."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 9200), timeout=0.5):
            return True
    except OSError:
        return False


def launch(app: str, cfg: dict, harness: dict | None = None) -> str:
    # Resolve the app first: "unknown app" / "not installed" are about the
    # request and read the same with or without a window manager. The
    # Hyprland gate applies only once we are about to exec through it.
    apps = _resolve_apps(cfg, harness)
    # soak fix: "browser" prefers BrowserOS (live logins) when its MCP
    # server is up — opt out with [agent] browseros_first = "false"
    if app in ("browser", "browser_new_tab") \
            and cfg.get("agent", {}).get("browseros_first",
                                         "true") == "true" \
            and shutil.which("browseros") and _browseros_live():
        down = _wm_down()
        if down:
            return down
        _exec_detached("browseros")
        return "LAUNCHED browser -> browseros"
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
    down = _wm_down()
    if down:
        return down
    _exec_detached(binname)
    return f"LAUNCHED {app} -> {binname}"


def focus(classname: str) -> str:
    from .. import platform
    down = _wm_down()
    if down:
        return down
    cmds = platform.focus_cmds(classname)
    if not cmds:
        return (f"SKIP (focus unsupported — "
                f"{platform.missing_deps_hint()})")
    if platform._try(cmds):
        return f"FOCUSED {classname}"
    return f"SKIP (no window matching class {classname!r})"


def close(classname: str) -> str:
    from .. import platform
    down = _wm_down()
    if down:
        return down
    if platform._try(platform.close_cmds(classname)):
        return f"CLOSED {classname or 'active window'}"
    return f"SKIP (nothing closed for {classname!r})"


def workspace(n: str) -> str:
    from .. import platform
    # natural-language args: "workspace 4", "ws4", "go to 4" all mean 4
    m = re.search(r"\d+", str(n))
    if not m:
        return f"SKIP (workspace {n!r} has no number)"
    num = int(m.group())
    down = _wm_down()
    if down:
        return down
    cmds = platform.workspace_cmds(num)
    if not cmds:
        return (f"SKIP (workspace {num} unsupported — "
                f"{platform.missing_deps_hint()})")
    platform._try(cmds)
    return f"WORKSPACE {num}"


def clients() -> list:
    """Open windows, as Hyprland reports them. Hyprland-only: no other
    platform has an equivalent enumerator here, so return [] instead of
    raising on a host without Hyprland."""
    from .. import platform
    if platform.current() != "linux":
        return []
    try:
        clients = hypr.query("clients")
    except hypr.HyprError:
        return []
    return clients if isinstance(clients, list) else []
