"""cua pointer backend and notification checks: cua *, notify test.

Nothing here starts or stops the cua-driver service. `cua enable` and
`cua disable` only edit the [pointer] backend key in wisp's config.
"""
import os
import pathlib
import shutil
import socket
import subprocess
import time

from .registry import CliError, GROUPS, command

GROUPS["cua"] = "The cua-driver pointer backend: status, test, log, enable"
GROUPS["notify"] = "Desktop notifications"


def socket_path() -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(
        "~/.cache/cua-driver/cua-driver.sock"))


def is_live() -> bool:
    from .. import platform
    try:
        return bool(platform._cua_live())
    except Exception:
        return False


@command("cua status", "Show whether the cua pointer backend is usable",
         ["wispd cua status", "wispd cua status --json"],
         {"configured": "str", "backend": "str|null", "mode": "str",
          "binary": "str|null", "socket": "str", "live": "bool"})
def cua_status(ctx, a):
    from .. import platform
    p = ctx.cfg.get("pointer", {})
    data = {"configured": p.get("backend", "auto"),
            "backend": platform.pointer_backend(ctx.cfg),
            "mode": p.get("mode", "guide"),
            "binary": shutil.which("cua-driver"),
            "socket": str(socket_path()), "live": is_live()}
    rows = [["configured", data["configured"]],
            ["active backend", data["backend"] or "none"],
            ["mode", data["mode"]],
            ["cua-driver", data["binary"] or "not on PATH"],
            ["socket", data["socket"]],
            ["driver", "reachable" if data["live"] else "not reachable"]]
    tones = [[None, None]] * 5 + [[None, "ok" if data["live"] else "fail"]]
    text = ctx.table(["", ""], rows, tones, header=False)
    if data["configured"] == "cua" and not data["live"]:
        if not ctx.json and not ctx.flags.quiet:
            print(text)
        raise CliError("E_CUA_DOWN", "The config selects cua but the "
                       "driver is not reachable.",
                       "start the cua-driver service yourself, then run "
                       "wispd cua test", data=data)
    return ctx.emit(data, text)


@command("cua test", "Check the driver binary and its socket (read only)",
         ["wispd cua test"], {"ok": "bool", "checks": "list"})
def cua_test(ctx, a):
    sock = socket_path()
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    exe = shutil.which("cua-driver")
    check("cua-driver on PATH", exe, exe or "not found")
    check("socket present", sock.exists(), str(sock))
    conn = False
    if sock.exists():
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(2)
        try:
            s.connect(str(sock))  # connect only; nothing is sent
            conn = True
        except OSError as e:
            check("socket accepts connections", False, str(e))
        finally:
            s.close()
        if conn:
            check("socket accepts connections", True, "connected")
    data = {"ok": all(c["ok"] for c in checks), "checks": checks}
    rows = [["ok" if c["ok"] else "FAIL", c["name"], c["detail"]]
            for c in checks]
    tones = [["ok" if c["ok"] else "fail", None, "muted"] for c in checks]
    text = ctx.table(["", "", ""], rows, tones, header=False)
    if data["ok"]:
        return ctx.emit(data, text)
    if not ctx.json and not ctx.flags.quiet:
        print(text)
    raise CliError("E_CUA_DOWN", hint="wispd cua status", data=data)


def _log_args(p):
    p.add_argument("-n", "--lines", type=int, default=50, metavar="N",
                   help="lines to show (default 50)")


@command("cua log", "Show the driver's recent journal lines (read only)",
         ["wispd cua log", "wispd cua log -n 200"], {"lines": "list"},
         args=_log_args)
def cua_log(ctx, a):
    cmd = ["journalctl", "--user", "-u", "cua-driver.service", "-n",
           str(a.lines), "--no-pager"]
    if not shutil.which("journalctl"):
        raise CliError("E_UNHEALTHY", "journalctl is not available.",
                       "wispd cua status")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CliError("E_FAILED", f"Reading the journal failed ({e}).",
                       "wispd cua status")
    lines = r.stdout.splitlines()
    return ctx.emit({"lines": lines}, "\n".join(lines) if lines else None)


def _set_backend(ctx, value: str) -> int:
    from . import settings
    previous = ctx.cfg.get("pointer", {}).get("backend", "auto")
    settings.set_key(ctx, "pointer.backend", value)
    note = ""
    if value == "cua" and not is_live():
        note = ("\nThe driver is not reachable yet. wisp never starts or "
                "stops the cua-driver service; start it yourself.")
    return ctx.emit({"backend": value, "previous": previous},
                    f"pointer.backend: {previous} -> {value}{note}")


@command("cua enable", "Select cua as the pointer backend (config only)",
         ["wispd cua enable"], {"backend": "str", "previous": "str"})
def cua_enable(ctx, a):
    return _set_backend(ctx, "cua")


@command("cua disable", "Switch the pointer backend away from cua "
         "(config only)", ["wispd cua disable"],
         {"backend": "str", "previous": "str"})
def cua_disable(ctx, a):
    from .. import platform
    alt = platform.pointer_backend(ctx.cfg, exclude=("cua",)) or "none"
    return _set_backend(ctx, alt)


@command("notify test", "Send one test notification",
         ["wispd notify test"], {"sent": "bool", "via": "str"})
def notify_test(ctx, a):
    body = "This is a test notification from wispd."
    try:
        from .. import notify as _n
        send = getattr(_n, "send", None)
    except ImportError:
        send = None
    if send is not None:
        # W18 notifier: dedupe, replace-id, actions, quiet hours
        # send(msg, level, *, cfg, key=...) returns a decision string
        # ("sent" | "disabled" | "quiet" | "deduped" ...) and delivers
        # async, so unique key defeats dedupe and join() waits for it.
        r = send(body, "info", cfg=ctx.cfg, key=f"notify-test:{time.time()}")
        getattr(getattr(_n, "_default", None), "join", lambda *a: None)()
        ok = r in ("sent", True)
        return ctx.emit({"sent": ok, "via": "wisp.notify"},
                        "sent" if ok else None)
    # TODO(W18): drop this fallback once wisp/notify.py is on the branch.
    from .. import platform
    cmd = platform.notify_cmd("Wisp", body)
    if not cmd or not shutil.which(cmd[0]):
        raise CliError("E_NO_NOTIFIER", hint="omarchy pkg add libnotify")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode:
        raise CliError("E_FAILED", f"{cmd[0]} exited {r.returncode}.",
                       "wispd doctor")
    return ctx.emit({"sent": True, "via": cmd[0]}, "sent")
