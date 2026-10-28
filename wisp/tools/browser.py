"""Watchable browser lane (B14): work in the user's own Chromium.

Ships behind `[browser] lane = "extension"`, off by default. The Wisp
extension (browser-extension/, an original MV3 extension) polls a socket
this module serves on 127.0.0.1 only. Nothing runs until the user pairs
the extension with a one-time code, each task gets its own tab group beside
the user's tabs, and Stop in the extension ends the lane for the turn.

Rules this module keeps (docs/BROWSER_LANE.md):
  - without pairing, every call fails with a setup message and does nothing
  - password, one-time-code and card fields are read but never filled
    (cua_safety.sensitive_field here, lib.js in the page)
  - refs come from one snapshot epoch; an older one is refused
  - at most MAX_STEPS steps in a batch, only http(s) pages are opened
  - the socket accepts only the extension's origin and a loopback Host,
    so a web page cannot talk to it (no DNS-rebinding, no CORS reach)
"""
import base64
import hmac
import http.server
import json
import queue
import re
import secrets
import threading
import time
import urllib.parse

from .. import config, cua_safety

DEFAULT_PORT = 47315
MAX_STEPS = 20
CODE_TTL_S = 300
MAX_BAD_CODES = 5
POLL_WAIT_S = 20.0
ALIVE_S = 45.0              # the extension polled this recently = paired
CALL_TIMEOUT_S = 60.0
MAX_BODY = 8 * 1024 * 1024  # a proof screenshot rides in one result
STEP_OPS = ("open", "snapshot", "click", "fill", "scroll", "wait_for",
            "screenshot", "keep", "done")

MSG_OFF = ("SKIP (the browser lane is off: set [browser] lane = \"extension\" "
           "with `wispd config set browser.lane extension`, then load "
           "browser-extension/ in your browser. Nothing was done.)")
MSG_STOPPED = ("REFUSED (you pressed Stop in the browser: the lane is off "
               "for this turn. Nothing was done.)")


def lane_mode(cfg: dict | None) -> str:
    v = str(((cfg or {}).get("browser", {}) or {}).get("lane", "off"))
    return v.strip().lower()


def enabled(cfg: dict | None) -> bool:
    return lane_mode(cfg) == "extension"


def port_of(cfg: dict | None) -> int:
    try:
        p = int(float(((cfg or {}).get("browser", {}) or {}).get("port", "")))
    except (TypeError, ValueError):
        return DEFAULT_PORT
    return p if 1024 <= p <= 65535 else DEFAULT_PORT


def setup_message(code: str) -> str:
    return (f"SKIP (the browser lane is not paired: open the Wisp extension "
            f"in your browser, press Pair and enter {code}. It works for "
            f"{CODE_TTL_S // 60} minutes. Nothing was done.)")


class Lane:
    """The pairing state, the command queue and the loopback server."""

    def __init__(self, port: int = 0, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._want_port = port
        self.port = 0
        self._server = None
        self._code = ""
        self._code_at = 0.0
        self._bad = 0
        self._token = ""
        self._last_poll = None
        self._cmds: queue.Queue = queue.Queue()
        self._waiting: dict = {}          # command id -> (event, [result])
        self._seq = 0
        self.stopped = threading.Event()  # Stop pressed in the extension
        self.turn = ""
        self.epoch = 0                    # latest snapshot epoch seen
        self.sensitive: set = set()       # refs of the latest snapshot
        self.refs: set = set()

    # -- server ---------------------------------------------------------
    def start(self) -> int:
        if self._server is not None:
            return self.port
        lane = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, status, body=None):
                data = json.dumps(body if body is not None else {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                origin = self.headers.get("Origin", "")
                if origin.startswith("chrome-extension://"):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Access-Control-Allow-Headers",
                                     "Content-Type, X-Wisp-Token")
                self.end_headers()
                self.wfile.write(data)

            def _gate(self) -> bool:
                """Loopback Host and the extension's Origin, or nothing."""
                host = self.headers.get("Host", "")
                if host not in (f"127.0.0.1:{lane.port}",
                                f"localhost:{lane.port}"):
                    self._send(403, {"error": "host"})
                    return False
                if not self.headers.get("Origin", "").startswith(
                        "chrome-extension://"):
                    self._send(403, {"error": "origin"})
                    return False
                return True

            def _body(self) -> dict:
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > MAX_BODY:
                    return {}
                try:
                    v = json.loads(self.rfile.read(n))
                except ValueError:
                    return {}
                return v if isinstance(v, dict) else {}

            def do_OPTIONS(self):
                if self._gate():
                    self._send(204)

            def do_POST(self):
                if not self._gate():
                    return
                path = urllib.parse.urlsplit(self.path).path
                body = self._body()
                if path == "/pair":
                    tok = lane.pair(str(body.get("code", "")))
                    return self._send(200, {"token": tok}) if tok \
                        else self._send(403, {"error": "bad or expired code"})
                if not lane.authorized(self.headers.get("X-Wisp-Token", "")):
                    return self._send(401, {"error": "token"})
                if path == "/poll":
                    try:
                        wait = min(float(body.get("wait", POLL_WAIT_S)),
                                   POLL_WAIT_S)
                    except (TypeError, ValueError):
                        wait = POLL_WAIT_S
                    return self._send(200, {"cmd": lane.next_command(wait)})
                if path == "/result":
                    lane.deliver(body)
                    return self._send(200)
                if path == "/stop":
                    lane.stop()
                    return self._send(200)
                self._send(404, {"error": "path"})

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True

        self._server = Server(("127.0.0.1", self._want_port), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever,
                         daemon=True).start()
        return self.port

    def close(self) -> None:
        srv, self._server = self._server, None
        if srv is not None:
            srv.shutdown()
            srv.server_close()

    # -- pairing ----------------------------------------------------------
    def new_code(self) -> str:
        """A fresh six-digit one-time code (replaces any earlier one)."""
        with self._lock:
            self._code = f"{secrets.randbelow(10 ** 6):06d}"
            self._code_at = self._clock()
            self._bad = 0
            return self._code

    def live_code(self) -> str:
        """The code still inside its window, else a new one."""
        with self._lock:
            ok = self._code and self._clock() - self._code_at < CODE_TTL_S \
                and self._bad < MAX_BAD_CODES
            code = self._code if ok else ""
        return code or self.new_code()

    def pair(self, code: str) -> str:
        """Session token for a right code; '' otherwise. A code works
        once, for CODE_TTL_S, and five wrong guesses burn it."""
        with self._lock:
            live = (self._code and self._bad < MAX_BAD_CODES
                    and self._clock() - self._code_at < CODE_TTL_S)
            if not live:
                return ""
            if not hmac.compare_digest(code.strip(), self._code):
                self._bad += 1
                return ""
            self._code = ""
            self._token = secrets.token_urlsafe(24)
            self._last_poll = self._clock()
            return self._token

    def authorized(self, token: str) -> bool:
        with self._lock:
            return bool(self._token) and hmac.compare_digest(
                token or "", self._token)

    @property
    def paired(self) -> bool:
        with self._lock:
            return bool(self._token) and self._last_poll is not None \
                and self._clock() - self._last_poll < ALIVE_S

    def unpair(self) -> None:
        with self._lock:
            self._token = ""
            self._last_poll = None

    # -- commands -----------------------------------------------------------
    def next_command(self, wait: float):
        with self._lock:
            self._last_poll = self._clock()
        try:
            cmd = self._cmds.get(timeout=max(0.0, wait))
        except queue.Empty:
            cmd = None
        with self._lock:
            self._last_poll = self._clock()
        return cmd

    def deliver(self, body: dict) -> None:
        with self._lock:
            slot = self._waiting.get(body.get("id"))
        if slot:
            slot[1].append(body)
            slot[0].set()

    def stop(self) -> None:
        """Stop pressed: this turn's pending calls end now."""
        self.stopped.set()
        with self._lock:
            slots = list(self._waiting.values())
        for ev, _ in slots:
            ev.set()

    def begin_turn(self, turn: str) -> bool:
        """A new turn clears a Stop and closes the last turn's tab group.
        Returns True when it cleared a Stop (the next command tells the
        extension to resume)."""
        with self._lock:
            if turn == self.turn:
                return False
            prev, self.turn = self.turn, turn
            self.epoch = 0
            self.refs, self.sensitive = set(), set()
        was_stopped = self.stopped.is_set()
        self.stopped.clear()
        if prev and not was_stopped:
            self._send_nowait({"op": "end_task", "task": prev})
        return was_stopped

    def _send_nowait(self, cmd: dict) -> None:
        with self._lock:
            self._seq += 1
            cmd["id"] = f"c{self._seq}"
        self._cmds.put(cmd)

    def call(self, cmd: dict, timeout: float = CALL_TIMEOUT_S) -> dict:
        """Send one command and wait for its result. Returns the result
        dict, or {"ok": False, "error": "stopped"|"timeout"}."""
        if self.stopped.is_set():
            return {"ok": False, "error": "stopped"}
        ev = threading.Event()
        slot = (ev, [])
        with self._lock:
            self._seq += 1
            cmd = dict(cmd, id=f"c{self._seq}")
            self._waiting[cmd["id"]] = slot
        self._cmds.put(cmd)
        try:
            ev.wait(timeout)
        finally:
            with self._lock:
                self._waiting.pop(cmd["id"], None)
        if self.stopped.is_set():
            return {"ok": False, "error": "stopped"}
        if not slot[1]:
            return {"ok": False, "error": "timeout"}
        return slot[1][0]

    # -- snapshot bookkeeping ------------------------------------------------
    def note_snapshot(self, snap: dict) -> None:
        els = snap.get("elements") or []
        with self._lock:
            self.epoch = int(snap.get("epoch") or 0)
            self.refs = {e.get("ref") for e in els}
            self.sensitive = {e.get("ref") for e in els
                              if e.get("sensitive")}


_LANE: Lane | None = None
_LANE_LOCK = threading.Lock()


def get_lane(cfg: dict | None = None) -> Lane:
    """The process-wide lane, its socket started on first use."""
    global _LANE
    with _LANE_LOCK:
        if _LANE is None:
            _LANE = Lane(port_of(cfg))
        _LANE.start()
        return _LANE


def reset_lane() -> None:
    """Close the socket and forget the lane (tests, config change)."""
    global _LANE
    with _LANE_LOCK:
        lane, _LANE = _LANE, None
    if lane is not None:
        lane.close()


# -- the tool -------------------------------------------------------------------

_REF = re.compile(r"^(\d+):(\d+)$")


def parse_steps(arg: str):
    """(steps, error). `arg` is JSON ({"steps": [...]}, a list, or one
    step) or one shorthand line: `snapshot`, `open <url>`, `click <ref>`,
    `fill <ref> <text>`, `wait_for <text>`, `scroll [dy]`, `screenshot`,
    `keep`, `done`."""
    a = (arg or "").strip()
    if not a:
        return None, "no steps"
    if a[0] in "[{":
        try:
            v = json.loads(a)
        except ValueError as e:
            return None, f"steps are not valid JSON ({e.msg})"
        if isinstance(v, dict) and "steps" in v:
            v = v["steps"]
        steps = v if isinstance(v, list) else [v]
    else:
        verb, _, rest = a.partition(" ")
        rest = rest.strip()
        step = {"do": verb.lower()}
        if verb.lower() == "open":
            step["url"] = rest
        elif verb.lower() in ("click",):
            step["ref"] = rest
        elif verb.lower() == "fill":
            ref, _, val = rest.partition(" ")
            step.update(ref=ref, value=val)
        elif verb.lower() == "wait_for":
            step["text"] = rest
        elif verb.lower() == "scroll" and rest:
            try:
                step["dy"] = int(rest)
            except ValueError:
                return None, "scroll takes a number of pixels"
        steps = [step]
    if not all(isinstance(s, dict) for s in steps):
        return None, "every step must be an object like {\"do\": \"open\"}"
    return steps, ""


def check_steps(steps: list, lane: Lane | None = None) -> str:
    """Refusal reason, or '' when the whole batch may be sent. Runs
    before anything leaves this process, so a refused batch does nothing."""
    if not steps:
        return "no steps"
    if len(steps) > MAX_STEPS:
        return f"too many steps ({len(steps)}; the most is {MAX_STEPS})"
    snap_epoch = lane.epoch if lane else 0
    refs = set(lane.refs) if lane else set()
    sens = set(lane.sensitive) if lane else set()
    for i, s in enumerate(steps, 1):
        op = str(s.get("do", ""))
        if op not in STEP_OPS:
            return f"step {i}: unknown step {op!r}"
        if op == "open":
            u = urllib.parse.urlsplit(str(s.get("url", "")).strip())
            if u.scheme not in ("http", "https") or not u.netloc:
                return (f"step {i}: only http and https pages can be "
                        "opened")
        if op == "snapshot":
            snap_epoch, refs, sens = -1, set(), set()   # ok until it runs
        if op in ("click", "fill"):
            ref = str(s.get("ref", "")).strip()
            m = _REF.match(ref)
            if not m:
                return (f"step {i}: {op} needs a ref like 3:7 from the "
                        "latest snapshot")
            if snap_epoch != -1 and int(m.group(1)) != snap_epoch:
                return (f"step {i}: stale ref {ref} (snapshot again; "
                        f"the latest is epoch {snap_epoch})")
            if op == "fill" and ref in sens:
                return (f"step {i}: {ref} is a password, one-time code or "
                        "card field and is never filled")
            if snap_epoch != -1 and refs and ref not in refs:
                return f"step {i}: no element {ref} in the latest snapshot"
    return ""


def _fmt_snapshot(r: dict) -> str:
    lines = [f"page {r.get('title', '')!r} {r.get('url', '')} "
             f"(tab {r.get('tab')}, epoch {r.get('epoch')})"]
    for e in r.get("elements") or []:
        mark = " [never filled]" if e.get("sensitive") else ""
        val = f" = {e['value']!r}" if e.get("value") else ""
        lines.append(f"  {e.get('ref')} {e.get('tag')}"
                     f"{'/' + e['type'] if e.get('type') else ''} "
                     f"{e.get('name', '')!r}{val}{mark}")
    text = (r.get("text") or "")[:1500]
    if text:
        lines.append("text: " + text)
    return "\n".join(lines)


def proof_dir(cfg: dict | None = None):
    return config.DATA_DIR / "browser" / "output"


def _save_proof(png_b64: str, task: str, n: int, out_dir) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", task)[:40] or "task"
    path = out_dir / f"proof-{safe}-{n}.png"
    path.write_bytes(base64.b64decode(png_b64))
    return str(path)


def run(arg: str, cfg: dict | None = None, *, lane: Lane | None = None,
        out_dir=None) -> str:
    """The `browser` tool. One call is one batch of up to MAX_STEPS steps."""
    cfg = cfg or {}
    if not enabled(cfg):
        return MSG_OFF
    lane = lane or get_lane(cfg)
    word = (arg or "").strip().lower()
    if word in ("pair", "status"):
        if lane.paired:
            return "OK (the browser lane is paired)"
        return setup_message(lane.live_code())
    steps, err = parse_steps(arg)
    if err:
        return f"SKIP ({err})"
    if not lane.paired:
        return setup_message(lane.live_code())
    if cua_safety.killed(cfg):
        return "REFUSED (cua kill switch is on)"
    from .. import trace
    turn = trace.current()
    resume = lane.begin_turn(turn)
    if lane.stopped.is_set():
        return MSG_STOPPED
    why = check_steps(steps, lane)
    if why:
        return f"REFUSED ({why})"
    for s in steps:
        cua_safety.audit_event(
            "browser", "browser", cfg, turn=turn, step=s.get("do"),
            **({"host": urllib.parse.urlsplit(str(s.get("url"))).netloc}
               if s.get("do") == "open" else {}),
            **({"chars": len(str(s.get("value", "")))}
               if s.get("do") == "fill" else {}))
    res = lane.call({"op": "batch", "task": turn, "steps": steps,
                     "resume": resume})
    if res.get("error") == "stopped":
        return MSG_STOPPED
    if res.get("error") == "timeout":
        return ("FAIL (the browser did not answer in time; is the "
                "extension still paired?)")
    out = []
    shots = 0
    for s, r in zip(steps, res.get("results") or []):
        op = s.get("do")
        if not r.get("ok"):
            out.append(f"{op}: FAILED {r.get('error', '')}")
            continue
        if op == "snapshot":
            lane.note_snapshot(r)
            out.append(_fmt_snapshot(r))
        elif op == "screenshot":
            shots += 1
            try:
                path = _save_proof(r.get("png", ""), turn, shots,
                                   out_dir or proof_dir(cfg))
                out.append(f"screenshot saved to {path}")
            except (ValueError, OSError) as e:
                out.append(f"screenshot: FAILED could not save it ({e})")
        elif op == "open":
            out.append(f"opened tab {r.get('tab')} in the Wisp tab group")
        else:
            out.append(f"{op}: ok")
    if not res.get("ok"):
        msg = res.get("error", "a step failed")
        return f"FAIL (browser: {msg})\n" + "\n".join(out)
    return f"OK (browser, {len(steps)} steps)\n" + "\n".join(out)
