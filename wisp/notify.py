"""Notifications (W18): one channel for the daemon and one API for tools.

Linux talks to org.freedesktop.Notifications through `gdbus` (no new
deps); the server is detected at runtime with GetServerInformation and
GetCapabilities (read-only calls). Without gdbus or a server it falls
back to `platform.notify_cmd` (notify-send / osascript / powershell),
which has no actions and no replace-id.

Behaviour: one toast per turn (replace-id), 60 s dedupe, quiet hours,
urgency from typed error codes, buttons only when the server advertises
`actions`, never blocks the caller, no toast for cancel or stale turns.
"""
import queue
import re
import subprocess
import threading
import time
from collections import OrderedDict
from datetime import datetime

LEVELS = ("info", "success", "attention", "error")
URGENCY = {"info": 0, "success": 0, "attention": 1, "error": 2}
TITLE = "Wisp"

# TODO(W17): move these into wisp/copy.py once it lands.
COPY = {
    "retry": "Retry",
    "open_log": "Open log",
    "heard_nothing": "Heard nothing",
}

# error code -> level; None means never toast (user already knows)
CODE_LEVEL = {
    "cancelled": None,
    "busy": "attention", "stale_prompt": "attention",
    "timeout": "attention", "ground_failed": "attention",
}

def for_code(code: str):
    """(level, text) for an error code: the level from CODE_LEVEL (None =
    no toast) and the body from the shared copy table, so a notification
    reads exactly like the bubble, console and bar."""
    from . import copy as _copy
    level = CODE_LEVEL.get(code, "error")
    return level, _copy.toast_text(code)


_DEST = "org.freedesktop.Notifications"
_PATH = "/org/freedesktop/Notifications"
_IFACE = "org.freedesktop.Notifications"


def gv_str(s: str) -> str:
    """GVariant text-format string literal."""
    s = (s.replace("\\", "\\\\").replace("'", "\\'")
         .replace("\n", "\\n").replace("\r", "\\r"))
    return f"'{s}'"


def _hm(s: str):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h * 60 + mi if h < 24 and mi < 60 else None


def in_quiet(spec: str, now: datetime) -> bool:
    """True when `now` falls in "HH:MM-HH:MM" (may cross midnight).
    Malformed or empty-width specs never silence anything."""
    a, _, b = (spec or "").partition("-")
    start, end = _hm(a), _hm(b)
    if start is None or end is None or start == end:
        return False
    cur = now.hour * 60 + now.minute
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def _run(argv, timeout=2.0):
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout
    except Exception:
        return 1, ""


def _monitor(secs: float):
    """Yield gdbus-monitor lines for `secs` seconds, then stop."""
    p = subprocess.Popen(
        ["gdbus", "monitor", "--session", "--dest", _DEST],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    timer = threading.Timer(secs, p.kill)
    timer.daemon = True
    timer.start()
    try:
        for line in p.stdout:
            yield line
    finally:
        timer.cancel()
        p.kill()
        p.wait()


class Notifier:
    def __init__(self, runner=None, clock=None, now=None, cfg=None,
                 sync=False, os_name=None, monitor=None):
        self._run = runner or _run
        self._clock = clock or time.monotonic
        self._now = now or datetime.now
        self.cfg = cfg or {}
        self.sync = sync
        self._os = os_name
        self._monitor = monitor or _monitor
        self._lock = threading.Lock()
        self._info = False  # False = not probed yet; None = no server
        self._turn_ids = OrderedDict()
        self._seen = {}
        self._q = queue.Queue()
        self._worker = None

    # -- config ------------------------------------------------------
    def _opt(self, key, default=""):
        return str(self.cfg.get("notify", {}).get(key, default))

    def _os_name(self):
        if self._os:
            return self._os
        from . import platform
        return platform.current()

    # -- server detection --------------------------------------------
    def server(self):
        """{"name", "vendor", "version", "caps"} or None when no
        notification server answers. Probed once, cached."""
        if self._info is not False:
            return self._info
        info = None
        base = ["gdbus", "call", "--session", "--dest", _DEST,
                "--object-path", _PATH, "--method"]
        rc, out = self._run(base + [f"{_IFACE}.GetServerInformation"])
        if rc == 0:
            parts = re.findall(r"'((?:[^'\\]|\\.)*)'", out)
            if parts:
                rc2, out2 = self._run(base + [f"{_IFACE}.GetCapabilities"])
                caps = (re.findall(r"'([^']*)'", out2) if rc2 == 0 else [])
                info = {"name": parts[0],
                        "vendor": parts[1] if len(parts) > 1 else "",
                        "version": parts[3] if len(parts) > 3 else "",
                        "caps": caps}
        self._info = info
        return info

    # -- public ------------------------------------------------------
    def send(self, msg, level="info", *, turn=None, code=None, key=None,
             actions=None, spoken=False, stale=False) -> str:
        """Decide synchronously, deliver asynchronously. Returns the
        decision: sent | disabled | cancelled | stale | quiet | spoken |
        deduped."""
        if self._opt("enabled", "true").lower() == "false":
            return "disabled"
        if code in CODE_LEVEL:
            level = CODE_LEVEL[code]
        elif code:
            level = "error"
        if level is None:
            return "cancelled"
        if level not in LEVELS:
            level = "info"
        if stale:
            return "stale"
        if (spoken and level in ("info", "success") and
                str(self.cfg.get("voice", {}).get("enabled", "false"))
                .lower() == "true"):
            return "spoken"
        if in_quiet(self._opt("quiet"), self._now()):
            return "quiet"
        window = float(self._opt("dedupe_secs", "60") or 60)
        dk = key or f"{level}:{msg}"
        with self._lock:
            now = self._clock()
            self._seen = {k: t for k, t in self._seen.items()
                          if now - t < window}
            if dk in self._seen:
                return "deduped"
            self._seen[dk] = now
        job = (msg, level, turn, list(actions or []))
        if self.sync:
            self._deliver(*job)
        else:
            self._q.put(job)
            if not (self._worker and self._worker.is_alive()):
                self._worker = threading.Thread(
                    target=self._loop, daemon=True)
                self._worker.start()
        return "sent"

    def join(self, timeout=2.0):
        end = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.01)

    # -- delivery ----------------------------------------------------
    def _loop(self):
        while True:
            try:
                job = self._q.get(timeout=5)
            except queue.Empty:
                return
            try:
                self._deliver(*job)
            except Exception:
                pass
            finally:
                self._q.task_done()

    def _deliver(self, msg, level, turn, actions):
        try:
            self._deliver_inner(msg, level, turn, actions)
        except Exception:
            pass  # a toast must never break a turn

    def _deliver_inner(self, msg, level, turn, actions):
        info = self.server() if self._os_name() == "linux" else None
        if info is None:
            from . import platform
            cmd = platform.notify_cmd(TITLE, msg)
            if cmd:
                self._run(cmd, timeout=3.0)
            return
        caps = info["caps"]
        body = msg
        if "body-markup" in caps:
            body = (msg.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;"))
        use_actions = (actions and "actions" in caps and
                       self._opt("actions", "true").lower() != "false")
        wire = ("[" + ", ".join(f"{gv_str(k)}, {gv_str(l)}"
                                for k, l, _ in actions) + "]"
                if use_actions else "[]")
        rid = self._turn_ids.get(turn, 0) if turn else 0
        ms = int(self._opt("timeout_ms", "5000") or 5000)
        argv = ["gdbus", "call", "--session", "--dest", _DEST,
                "--object-path", _PATH, "--method", f"{_IFACE}.Notify",
                TITLE, str(rid), "", gv_str(TITLE), gv_str(body), wire,
                "{'urgency': <byte %d>}" % URGENCY[level], str(ms)]
        rc, out = self._run(argv, timeout=3.0)
        m = re.search(r"uint32 (\d+)", out)
        if rc != 0 or not m:
            from . import platform
            cmd = platform.notify_cmd(TITLE, msg)
            if cmd:
                self._run(cmd, timeout=3.0)
            return
        nid = int(m.group(1))
        if turn:
            self._turn_ids[turn] = nid
            self._turn_ids.move_to_end(turn)
            while len(self._turn_ids) > 32:
                self._turn_ids.popitem(last=False)
        if use_actions:
            handlers = {k: fn for k, _, fn in actions}
            if self.sync:
                self._listen(nid, handlers)
            else:
                threading.Thread(target=self._listen, args=(nid, handlers),
                                 daemon=True).start()

    def _listen(self, nid, handlers):
        pat = re.compile(r"ActionInvoked \(uint32 (\d+), '([^']*)'\)")
        try:
            for line in self._monitor(30.0):
                m = pat.search(line)
                if m and int(m.group(1)) == nid:
                    fn = handlers.get(m.group(2))
                    if fn:
                        try:
                            fn()
                        except Exception:
                            pass
                    return
        except Exception:
            pass


_default = Notifier()


def send(msg, level="info", *, cfg=None, **kw) -> str:
    if cfg is None:
        try:
            from . import config
            cfg = config.load_config()
        except Exception:
            cfg = {}
    _default.cfg = cfg
    return _default.send(msg, level, **kw)
