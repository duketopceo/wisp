"""`wispd settings`: open the settings window (overhaul plan U4).

The window is its own Quickshell config (`shells/settings`), so it never
dies with the bar shell and never sits in the daemon's action queue. One
path for the CLI and the launcher's Settings action:

1. Ask a running window to open the category over Quickshell IPC
   (`quickshell ipc -p <dir> call settings open <category>`).
2. When no window answers, start one detached (its own session) with the
   category in WISP_SETTINGS_CATEGORY, which `shell.qml` reads at start.
3. Focus it through Hyprland by title: a Wayland client cannot raise
   itself. When that fails, say where the window is instead of failing.

With no Wayland or X display it exits non-zero and points at
`wispd config` and `wispd tui`.
"""
import os
import pathlib
import shutil
import subprocess

from .. import settings_schema
from .registry import CliError, command

WINDOW_TITLE = "Wisp settings"
CATEGORY_ENV = "WISP_SETTINGS_CATEGORY"
IPC_TIMEOUT_S = 3


def shell_dir() -> pathlib.Path:
    """The settings Quickshell config shipped beside the `wisp` package."""
    return pathlib.Path(__file__).resolve().parent.parent.parent \
        / "shells" / "settings"


def has_display(env) -> bool:
    return bool(env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"))


def ipc_argv(qs: str, path, category: str) -> list:
    return [qs, "ipc", "-p", str(path), "call", "settings", "open",
            category]


def launch_argv(qs: str, path) -> list:
    return [qs, "-n", "-p", str(path)]


def launch_env(env, category: str) -> dict:
    out = dict(env)
    out.pop(CATEGORY_ENV, None)
    if category:
        out[CATEGORY_ENV] = category
    return out


def focus_lua() -> str:
    from .. import hypr
    return hypr.focus_window("title:^" + WINDOW_TITLE + "$")


def open_window(category: str = "", env=None, run=subprocess.run,
                spawn=subprocess.Popen, which=shutil.which,
                focus=None, path=None) -> dict:
    """Raise a running window or start one. Returns what it did:
    {"action": "raised"|"started", "category": ..., "focused": bool}.
    Raises CliError when there is no display or no quickshell."""
    env = os.environ if env is None else env
    if not has_display(env):
        raise CliError("E_NO_DISPLAY")
    qs = which("quickshell") or which("qs")
    if not qs:
        raise CliError("E_UNHEALTHY", "quickshell is not installed.",
                       "wispd doctor")
    path = shell_dir() if path is None else path
    try:
        r = run(ipc_argv(qs, path, category), capture_output=True,
                text=True, timeout=IPC_TIMEOUT_S, env=dict(env))
        running = r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        running = False
    if not running:
        spawn(launch_argv(qs, path), env=launch_env(env, category),
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, start_new_session=True)
    focused = _focus(focus) if running else False
    return {"action": "raised" if running else "started",
            "category": category, "focused": focused}


def _focus(focus=None) -> bool:
    """Best effort: ask Hyprland to focus the window. True only on a clean
    'ok' reply; Hyprland answers 'warning: ...' when no window matches."""
    if focus is None:
        from .. import hypr
        focus = hypr.eval_lua
    try:
        return focus(focus_lua()) == "ok"
    except Exception:  # noqa: BLE001
        return False


def _args(p):
    p.add_argument("--category", choices=list(settings_schema.CATEGORIES),
                   default="", metavar="NAME",
                   help="page to open: " + ", ".join(
                       settings_schema.CATEGORIES))


@command("settings", "Open the settings window",
         ["wispd settings", "wispd settings --category budget"],
         {"action": "str", "category": "str", "focused": "bool"},
         args=_args)
def settings(ctx, a):
    res = open_window(a.category)
    if res["action"] == "started":
        text = "Opening the settings window."
    elif res["focused"]:
        text = "The settings window is open."
    else:
        text = ("The settings window is already open on another "
                "workspace.")
    return ctx.emit(res, text)
