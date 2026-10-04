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

from .. import probes_cua
from .registry import CliError, GROUPS, command

GROUPS["cua"] = "The cua-driver pointer backend: status, test, log, kill, enable"
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
          "binary": "str|null", "socket": "str", "live": "bool",
          "state": "str", "fix": "str|null", "kill": "bool",
          "dry_run": "bool", "version": "str|null"})
def cua_status(ctx, a):
    from .. import platform
    p = ctx.cfg.get("pointer", {})
    probe = probes_cua.CuaProbe(ctx.cfg).check(version=False)
    data = {"configured": p.get("backend", "auto"),
            "backend": platform.pointer_backend(ctx.cfg),
            "mode": p.get("mode", "guide"),
            "binary": shutil.which("cua-driver"),
            "socket": str(socket_path()), "live": is_live(),
            "state": probe["state"], "fix": probe["fix"],
            "kill": probe["kill"], "dry_run": probe["dry_run"],
            "version": probe["version"]}
    rows = [["configured", data["configured"]],
            ["active backend", data["backend"] or "none"],
            ["mode", data["mode"]],
            ["cua-driver", data["binary"] or "not on PATH"],
            ["socket", data["socket"]],
            ["driver", "reachable" if data["live"] else "not reachable"],
            ["state", data["state"].replace("_", " ")]]
    tones = [[None, None]] * 5 + [[None, "ok" if data["live"] else "fail"],
                                  [None, None]]
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
    p.add_argument("--audit", action="store_true",
                   help="show wisp's own cua audit log instead")


@command("cua log", "Show the driver journal, or the audit log (read only)",
         ["wispd cua log", "wispd cua log --audit -n 20"],
         {"lines": "list"},
         args=_log_args)
def cua_log(ctx, a):
    if a.audit:
        from .. import cua_safety
        try:
            text = cua_safety.audit_default_path().read_text()
        except OSError:
            text = ""
        lines = text.splitlines()[-max(a.lines, 0):] if a.lines else []
        return ctx.emit({"lines": lines},
                        "\n".join(lines) if lines else None)
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


@command("cua kill", "Arm the kill switch: refuse all cua input at once",
         ["wispd cua kill"], {"armed": "bool", "path": "str"})
def cua_kill(ctx, a):
    from .. import cua_safety
    p = cua_safety.kill_default_path()
    cua_safety.kill(p)
    return ctx.emit({"armed": True, "path": str(p)},
                    f"kill switch armed ({p}); undo with wispd cua resume")


@command("cua resume", "Clear the kill switch file",
         ["wispd cua resume"],
         {"armed": "bool", "path": "str", "config_kill": "bool"})
def cua_resume(ctx, a):
    from .. import cua_safety
    p = cua_safety.kill_default_path()
    cua_safety.resume(p)
    cfg_kill = cua_safety.settings(ctx.cfg)["kill"]
    note = ""
    if cfg_kill:
        note = "\n[cua] kill_switch is still true in config: input stays refused."
    return ctx.emit({"armed": bool(cfg_kill), "path": str(p),
                     "config_kill": bool(cfg_kill)},
                    "kill switch file cleared" + note)


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
        import importlib
        _n = importlib.import_module("wisp.notify")
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
