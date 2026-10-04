"""Behaviour of the fake executables (runs as a subprocess; stdlib only).

Dispatches on the tool name: cua-driver, hyprctl, notify-send,
systemctl. Config: ``<name>.json`` beside this file. Calls: appended to
``calls.jsonl`` (one write per line, O_APPEND)."""
import fcntl
import json
import os
import pathlib
import socket
import sys
import time

DIR = pathlib.Path(__file__).resolve().parent


def _cfg(name: str) -> dict:
    p = DIR / f"{name}.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _log(name: str, argv: list, **extra) -> None:
    row = {"bin": name, "argv": argv, "t": time.time(), **extra}
    fd = os.open(DIR / "calls.jsonl", os.O_WRONLY | os.O_APPEND
                 | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(row) + "\n").encode())
    finally:
        os.close(fd)


class _Locked:
    """Read-modify-write a JSON state file under an flock."""

    def __init__(self, name: str, default):
        self.path = DIR / f"{name}.state.json"
        self.default = default

    def __enter__(self):
        self.fh = open(str(self.path) + ".lock", "w")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = self.default
        return self.data

    def __exit__(self, *exc):
        self.path.write_text(json.dumps(self.data))
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


# -- cua-driver -----------------------------------------------------

def cua_driver(argv: list) -> int:
    cfg = _cfg("cua-driver")
    if argv[:1] != ["call"] or len(argv) < 2:
        _log("cua-driver", argv, ok=True)
        print(json.dumps({"ok": True, "version": "fake"}))
        return 0
    tool = argv[1]
    try:
        args = json.loads(argv[2]) if len(argv) > 2 else {}
    except ValueError:
        sys.stderr.write("E_CUA_BAD_ARGS: arguments are not JSON\n")
        _log("cua-driver", argv, ok=False)
        return 2
    sock = cfg.get("socket") or os.path.expanduser(
        "~/.cache/cua-driver/cua-driver.sock")
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(float(cfg.get("connect_timeout", 5)))
    try:
        s.connect(sock)
    except OSError as e:
        sys.stderr.write(f"E_CUA_DOWN: cannot reach daemon at {sock}: "
                         f"{e}\n")
        _log("cua-driver", argv, ok=False, down=True)
        return 1
    s.settimeout(None)  # a hung daemon is the caller's timeout to kill
    s.sendall((json.dumps({"tool": tool, "args": args}) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    try:
        rep = json.loads(buf)
    except ValueError:
        sys.stderr.write("E_CUA_PROTOCOL: empty or malformed reply\n")
        _log("cua-driver", argv, ok=False)
        return 1
    _log("cua-driver", argv, ok=bool(rep.get("ok")))
    if rep.get("ok"):
        print(json.dumps(rep))
        return 0
    sys.stderr.write(f"{rep.get('error', 'E_CUA_FAILED')}\n")
    return 1


# -- hyprctl --------------------------------------------------------

def hyprctl(argv: list) -> int:
    rd = os.environ.get("XDG_RUNTIME_DIR", "")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    path = os.path.join(rd, "hypr", sig, ".socket.sock")
    args = [a for a in argv if a not in ("-j",)]
    if argv[:1] == ["-j"] and args:
        req = "j/" + " ".join(args)
    else:
        req = " ".join(args)
    _log("hyprctl", argv, request=req)
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    try:
        s.connect(path)
        s.sendall(req.encode())
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    except OSError as e:
        sys.stderr.write(f"hyprctl: cannot reach {path}: {e}\n")
        return 1
    sys.stdout.write(data.decode())
    return 0


# -- notification server state (shared by notify-send and gdbus) ----

def _notify_store(title: str, body: str, replaces: int) -> int:
    with _Locked("notify", {"next": 1, "live": {}, "signals": []}) as st:
        nid = replaces or st["next"]
        if not replaces:
            st["next"] += 1
        st["live"][str(nid)] = {"title": title, "body": body}
    return nid


def _signal(kind: str, args: list, delay_ms: int = 0) -> None:
    with _Locked("notify", {"next": 1, "live": {}, "signals": []}) as st:
        st["signals"].append({"kind": kind, "args": args,
                              "at": time.time() + delay_ms / 1000.0})


# -- notify-send ----------------------------------------------------

def notify_send(argv: list) -> int:
    cfg = _cfg("notify")
    opts = {"app": "", "urgency": "normal", "timeout": -1, "icon": "",
            "category": "", "replaces": 0, "print_id": False,
            "wait": False, "actions": [], "hints": [], "transient": False}
    pos: list = []
    i = 0
    take = {"-a": "app", "--app-name": "app", "-u": "urgency",
            "--urgency": "urgency", "-t": "timeout",
            "--expire-time": "timeout", "-i": "icon", "--icon": "icon",
            "-c": "category", "--category": "category",
            "-r": "replaces", "--replace-id": "replaces"}
    while i < len(argv):
        a = argv[i]
        key, val = a, None
        if a.startswith("--") and "=" in a:
            key, val = a.split("=", 1)
        if key in take:
            if val is None:
                i += 1
                val = argv[i] if i < len(argv) else ""
            opts[take[key]] = int(val) if take[key] in (
                "timeout", "replaces") and val.lstrip("-").isdigit() \
                else val
        elif key in ("-A", "--action"):
            if val is None:
                i += 1
                val = argv[i] if i < len(argv) else ""
            name, _, label = val.partition("=")
            opts["actions"].append({"name": name, "label": label})
        elif key in ("-h", "--hint"):
            if val is None:
                i += 1
                val = argv[i] if i < len(argv) else ""
            opts["hints"].append(val)
        elif key in ("-p", "--print-id"):
            opts["print_id"] = True
        elif key in ("-w", "--wait"):
            opts["wait"] = True
        elif key in ("-e", "--transient"):
            opts["transient"] = True
        elif a == "--":
            pos.extend(argv[i + 1:])
            break
        elif a.startswith("-") and len(a) > 1:
            pass
        else:
            pos.append(a)
        i += 1
    title = pos[0] if pos else ""
    body = pos[1] if len(pos) > 1 else ""
    nid = _notify_store(title, body, int(opts["replaces"]))
    row = dict(opts, id=nid, title=title, body=body, via="notify-send")
    _log("notify-send", argv, notification=row)
    if cfg.get("latency_ms"):
        time.sleep(cfg["latency_ms"] / 1000.0)
    if opts["print_id"]:
        print(nid)
    if opts["wait"] and opts["actions"] and cfg.get("invoke"):
        print(cfg["invoke"])
    if cfg.get("exit"):
        sys.stderr.write("notify-send: scripted failure\n")
    return int(cfg.get("exit", 0))


# -- gdbus (org.freedesktop.Notifications, as quickshell serves it) ---

def _parse_gv(text: str):
    """Tiny GVariant-text parser: strings, ints (optional type tag),
    bools, arrays, dicts (kept as their text). Enough for Notify args."""
    t = text.strip()
    for tag in ("uint32 ", "int32 ", "uint64 ", "int64 ", "byte ",
                "@as ", "@a{sv} "):
        if t.startswith(tag):
            t = t[len(tag):].strip()
    if t[:1] in ("'", '"'):
        q, out, i = t[0], [], 1
        while i < len(t) and t[i] != q:
            if t[i] == "\\" and i + 1 < len(t):
                i += 1
                out.append({"n": "\n", "r": "\r"}.get(t[i], t[i]))
                i += 1
                continue
            out.append(t[i])
            i += 1
        return "".join(out)
    if t.startswith("["):
        inner, items, cur, q, depth = t[1:t.rindex("]")], [], "", "", 0
        for ch in inner:
            if q:
                cur += ch
                if ch == q:
                    q = ""
            elif ch in "'\"":
                q = ch
                cur += ch
            elif ch in "[{(":
                depth += 1
                cur += ch
            elif ch in "]})":
                depth -= 1
                cur += ch
            elif ch == "," and depth == 0:
                items.append(cur)
                cur = ""
            else:
                cur += ch
        if cur.strip():
            items.append(cur)
        return [_parse_gv(i) for i in items]
    if t.startswith("{"):
        return t
    if t in ("true", "false"):
        return t == "true"
    try:
        return int(t)
    except ValueError:
        return t


def _gv_str(v: str) -> str:
    return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"


NOTIF = "org.freedesktop.Notifications"
CAPS = ["persistence", "body", "body-markup", "body-hyperlinks",
        "actions", "icon-static"]


def gdbus(argv: list) -> int:
    cfg = _cfg("notify")
    if "--system" in argv:
        _log("gdbus", argv, violation="system bus")
        sys.stderr.write("fake gdbus: refusing --system bus\n")
        return 1
    verb = argv[0] if argv else ""
    if verb == "monitor":
        _log("gdbus", argv, monitor=True)
        return _gdbus_monitor()
    if verb != "call":
        _log("gdbus", argv)
        sys.stderr.write(f"fake gdbus: unsupported {verb!r}\n")
        return 1
    method, params, i = "", [], 1
    while i < len(argv):
        a = argv[i]
        if a in ("--method", "-m"):
            i += 1
            method = argv[i]
        elif a in ("--dest", "-d", "--object-path", "-o", "--timeout",
                   "-t"):
            i += 1
        elif not method and a.startswith("-"):
            pass  # options precede the positional params
        else:
            params.append(a)
        i += 1
    if cfg.get("server_down"):
        _log("gdbus", argv, method=method, down=True)
        sys.stderr.write("Error: GDBus.Error:org.freedesktop.DBus.Error."
                         "ServiceUnknown: The name org.freedesktop."
                         "Notifications was not provided by any .service "
                         "files\n")
        return 1
    name = method.rsplit(".", 1)[-1]
    if cfg.get("latency_ms"):
        time.sleep(cfg["latency_ms"] / 1000.0)
    if name == "Notify" and len(params) >= 8:
        app, rid, icon, summary, body, acts, hints, tmo = (
            _parse_gv(p) for p in params[:8])
        acts = acts if isinstance(acts, list) else []
        nid = _notify_store(summary, body, int(rid or 0))
        row = {"id": nid, "replaces": int(rid or 0), "app": app,
               "icon": icon, "title": summary, "body": body,
               "actions": [{"name": acts[k], "label": acts[k + 1]
                            if k + 1 < len(acts) else ""}
                           for k in range(0, len(acts), 2)],
               "hints": hints, "timeout": int(tmo), "via": "gdbus"}
        _log("gdbus", argv, method=name, notification=row)
        ai = cfg.get("auto_invoke")
        if ai and row["actions"]:
            act = ai.get("action") or row["actions"][0]["name"]
            _signal("ActionInvoked", [nid, act], ai.get("delay_ms", 0))
        print(f"(uint32 {nid},)")
        return 0
    _log("gdbus", argv, method=name)
    if name == "GetCapabilities":
        caps = cfg.get("capabilities", CAPS)
        print("([" + ", ".join(_gv_str(c) for c in caps) + "],)")
    elif name == "GetServerInformation":
        print("('quickshell', 'outfoxxed', '0.2.0', '1.2')")
    elif name == "CloseNotification" and params:
        nid = int(_parse_gv(params[0]))
        with _Locked("notify", {"next": 1, "live": {},
                                "signals": []}) as st:
            st["live"].pop(str(nid), None)
        _signal("NotificationClosed", [nid, 3])
        print("()")
    else:
        sys.stderr.write(f"fake gdbus: unknown method {method}\n")
        return 1
    return 0


def _gdbus_monitor() -> int:
    """Print signals as `gdbus monitor` does, forever (the caller kills
    it). Signals are scheduled by `at` so a delayed invoke arrives late."""
    done = 0
    idle_limit = _cfg("notify").get("monitor_idle_s")
    last = time.time()
    while True:
        with _Locked("notify", {"next": 1, "live": {},
                                "signals": []}) as st:
            sigs = list(st["signals"])
        now = time.time()
        while done < len(sigs) and sigs[done]["at"] <= now:
            sg = sigs[done]
            done += 1
            if sg["kind"] == "ActionInvoked":
                args = f"(uint32 {sg['args'][0]}, {_gv_str(sg['args'][1])})"
            else:
                args = (f"(uint32 {sg['args'][0]}, "
                        f"uint32 {sg['args'][1]})")
            try:
                print(f"/org/freedesktop/Notifications: {NOTIF}."
                      f"{sg['kind']} {args}", flush=True)
            except BrokenPipeError:
                return 0
            last = now
        if idle_limit and now - last > idle_limit:
            return 0
        time.sleep(0.02)


# -- systemctl ------------------------------------------------------

def _unit(name: str) -> str:
    return name if "." in name else name + ".service"


def systemctl(argv: list) -> int:
    cfg = _cfg("systemctl")
    rest = [a for a in argv if a != "--user"]
    user = "--user" in argv
    flags = [a for a in rest if a.startswith("-")]
    rest = [a for a in rest if not a.startswith("-")]
    if not user:
        _log("systemctl", argv, violation="system scope")
        sys.stderr.write("fake systemctl: refusing system scope "
                         "(only --user is faked)\n")
        return 1
    verb, units = (rest[0] if rest else ""), [_unit(u) for u in rest[1:]]
    default = {n if "." in n else n + ".service":
               (v if isinstance(v, dict) else {"state": v})
               for n, v in cfg.get("units", {}).items()}
    code = 0
    out: list = []
    with _Locked("systemctl", default) as st:
        for u in units:
            if verb in ("daemon-reload", "reset-failed") and not units:
                break
            if u not in st:
                sys.stderr.write(f"Unit {u} not found.\n")
                code = 5
                continue
            ent = st[u]
            if verb in ("start", "restart", "reload-or-restart"):
                if ent.get("start_ok", True):
                    ent["state"] = "active"
                else:
                    ent["state"] = "failed"
                    sys.stderr.write(f"Job for {u} failed.\n")
                    code = 1
            elif verb == "stop":
                ent["state"] = "inactive"
            elif verb == "reset-failed":
                if ent.get("state") == "failed":
                    ent["state"] = "inactive"
            elif verb == "is-active":
                out.append(ent.get("state", "inactive"))
                if ent.get("state") != "active":
                    code = 3
            elif verb == "is-enabled":
                out.append("enabled")
            elif verb in ("status", "show"):
                out.append(f"{u} {ent.get('state', 'inactive')}")
                if ent.get("state") != "active":
                    code = 3
    _log("systemctl", argv, verb=verb, units=units, code=code)
    if out:
        print("\n".join(out))
    return code


TOOLS = {"cua-driver": cua_driver, "hyprctl": hyprctl,
         "notify-send": notify_send, "gdbus": gdbus,
         "systemctl": systemctl}


def main(name: str) -> int:
    return TOOLS[name](sys.argv[1:])
