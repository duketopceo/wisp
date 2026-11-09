"""browser *: the native messaging host for the Wisp browser extension.

`install-host` writes a small launcher and one host manifest per browser
under your home directory, and nothing else. `uninstall-host` removes
exactly those files. `status` reads and connects to nothing but the
manifests and wispd's own socket.
"""
import pathlib
import sys

from .. import config
from ..tools import browser_nm
from .registry import CliError, GROUPS, command

GROUPS["browser"] = "The browser lane: install the extension's native host"


def _install_args(p):
    p.add_argument("--browser", action="append", default=None,
                   choices=sorted(browser_nm.BROWSERS), metavar="NAME",
                   help="browser to set up (repeatable); default: every "
                        "supported browser found")
    p.add_argument("--extension-id", action="append", default=[],
                   metavar="ID", help="an extension id allowed to connect "
                   "(repeatable)")
    p.add_argument("--dev", action="store_true",
                   help="also allow the unpacked development build "
                        "(pinned id " + browser_nm.DEV_EXTENSION_ID + ")")


@command("browser install-host",
         "Set up the native host so the Wisp extension can connect",
         ["wispd browser install-host --dev",
          "wispd browser install-host --extension-id <id> --browser chromium"],
         {"launcher": "str", "manifests": "list"}, _install_args)
def install_host(ctx, a):
    ids = list(a.extension_id) + ([browser_nm.DEV_EXTENSION_ID]
                                  if a.dev else [])
    wispd = pathlib.Path(ctx.host.__file__).resolve()
    try:
        data = browser_nm.install_host(
            pathlib.Path.home(), config.DATA_DIR, sys.executable,
            str(wispd), ids, a.browser)
    except ValueError as e:
        raise CliError("E_USAGE", f"{e}.", "wispd browser install-host "
                       "--help")
    rows = [[m["browser"], m["path"],
             "" if m["documented"] else "path not in the Chrome docs"]
            for m in data["manifests"]]
    text = ctx.table(["browser", "manifest", "note"], rows)
    text += (f"\nlauncher: {data['launcher']}\n"
             "Next: wispd config set browser.lane extension, then press "
             "Connect in the extension.")
    return ctx.emit(data, text)


@command("browser uninstall-host",
         "Remove the native host files wispd browser install-host wrote",
         ["wispd browser uninstall-host"], {"removed": "list"})
def uninstall_host(ctx, a):
    removed = browser_nm.uninstall_host(config.DATA_DIR)
    text = "\n".join(removed) if removed else "nothing was installed"
    return ctx.emit({"removed": removed}, text)


@command("browser status",
         "Show the native host files, and whether wispd serves the lane",
         ["wispd browser status", "wispd browser status --json"],
         {"browsers": "list", "launcher": "str", "launcher_ok": "bool",
          "socket": "str", "socket_mode": "str", "socket_live": "bool"})
def status(ctx, a):
    data = browser_nm.status(pathlib.Path.home(), config.DATA_DIR,
                             config.RUN_DIR / browser_nm.SOCKET_NAME)
    rows = [[b["browser"], "installed" if b["installed"] else "-",
             ", ".join(b["origins"]) or "",
             "" if b["documented"] else "path not in the Chrome docs"]
            for b in data["browsers"]]
    tones = [[None, "ok" if b["installed"] else "muted", None, "muted"]
             for b in data["browsers"]]
    text = ctx.table(["browser", "host", "allowed", "note"], rows, tones)
    text += (f"\nlauncher: {'ok' if data['launcher_ok'] else 'missing'}"
             f"\nsocket: {data['socket']} "
             f"{'serving' if data['socket_live'] else 'not serving'}"
             f"{' mode ' + data['socket_mode'] if data['socket_mode'] else ''}")
    return ctx.emit(data, text)
