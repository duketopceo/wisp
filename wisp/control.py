"""Per-app control channels (U3, KTD3): a JSON-lines client and an
app -> endpoint registry. FilmCraft ships the first channel
(`filmcraft --control 9876`; ../artcraft/filmcraft/docs/
control-protocol.md): `ui.elements` exposes every on-screen widget's
automation id, label and rect — ground truth the grounding chain and
the verify ladder can lean on where AT-SPI is thin (egui reports
almost nothing).

Two consumers, one module:

- grounding: `_control` in wisp/grounding.py resolves a click-by-name
  through `ui.elements` — the element rect CENTER dispatches through
  the standard cua pixel path (recorded by U1, verified by U2), never
  `ui.click`: training the grounding chain is the settled point and a
  channel-dispatched click would skip the instrumentation being
  measured. `ui.click`/`ui.screenshot` stay on the client for drills
  and the U5 observe path.

- verify: `verify_rung` diffs the `ui.inspect`/`ui.elements` snapshots
  captured around dispatch (before at aim time, after at verify time,
  both persisted into the recorded turn's action dir). It corroborates
  — never sole-sources a label-grade `landed` (R2a): it votes and lets
  the ladder reconcile, and abstains cleanly on any channel trouble.

Trust model: the channel is UNAUTHENTICATED loopback — a process
squatting on the port can serve forged rects and forged diffs. Two
guards follow: element rects (window-local egui points) are validated
against the app's live compositor window bounds (hypr clients / cua
list_windows — never the channel's own report) before a click
dispatches, and the rung corroborates rather than deciding. Wire data
is untrusted text: ids/labels/state are size-bounded and control
characters stripped at parse, fields stay quoted JSON values wherever
they land.
"""
import dataclasses
import json
import math
import pathlib
import re
import socket
import time

# -- protocol bounds (server side: apps/filmcraft/src/control_server.rs)
MAX_LINE = 4 * 1024 * 1024     # the server's own per-line cap
MAX_SKIP = 16                  # malformed lines tolerated per call
MAX_REQ_BYTES = 64 * 1024      # requests we emit stay far under it
CONNECT_S = 0.4                # loopback connect budget
READ_S = 3.5                   # server defers Retry answers ~3 s
SCREENSHOT_READ_S = 15.0       # ui.screenshot can stall ~10 s
PENDING_CAP = 16               # remembered pre-dispatch snapshots
ID_CAP = 256                   # element id / label field cap
STR_CAP = 512                  # generic string field cap
ELEMENT_CAP = 1024             # parsed elements per reply
FLAT_CAP = 256                 # flattened inspect keys compared
INSPECT_NODES = 4096           # sanitized inspect node budget
EVIDENCE_CAP = 256 * 1024      # bytes per control_*.json artifact
RECT_MAX = 32768.0             # bound on channel-supplied coordinates
SLACK_PX = 8.0                 # edge slack for the center-in-window check

_METHOD = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,63}$")
_APP_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_TOO_LONG = object()
_MISSING = object()

# inspect fields that jitter every frame — a diff that fires on these
# alone cannot tell a landed action from a running playback clock
_VOLATILE = frozenset({
    "fps", "audioclock", "dropped", "shown", "preroll"})

_LOOPBACK = ("127.0.0.1", "localhost", "::1")


class ControlError(Exception):
    """code: down (refused/EOF) | timeout | refused (ok:false) |
    protocol (no usable reply inside the bounds). `refused` is a real
    answer — the others may retry once on a fresh connection."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


# ------------------------------------------------------------ text bounds

def _clean(v, cap: int = STR_CAP) -> str:
    """Untrusted wire text -> a safe, bounded string: control
    characters stripped (they'd smuggle escapes into prompts, step
    records and pack manifests), length capped."""
    s = "".join(ch for ch in str(v or "")
                if ch >= " " and ch != "\x7f")
    return s[:cap]


def _num(v):
    """Finite float or None — NaN/inf/garbage never reaches a rect."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _rect(v):
    """[x, y, w, h] floats or None — the channel's rect shape."""
    if isinstance(v, dict):
        v = [v.get("x"), v.get("y"),
             v.get("width", v.get("w")), v.get("height", v.get("h"))]
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return None
    r = tuple(_num(n) for n in v)
    if any(n is None for n in r):
        return None
    x, y, w, h = r
    if w <= 0 or h <= 0 or abs(x) > RECT_MAX or abs(y) > RECT_MAX \
            or w > RECT_MAX or h > RECT_MAX:
        return None
    return r


def _bounded(v, depth=0, _b=None):
    """Deep-sanitize channel JSON: depth-capped, node-capped, strings
    cleaned — the result is safe to persist into the action dir or to
    quote into a judge prompt."""
    b = _b if _b is not None else [INSPECT_NODES]
    if b[0] <= 0:
        return None
    b[0] -= 1
    if isinstance(v, dict):
        return {str(_clean(k, 64)): _bounded(val, depth + 1, b)
                for k, val in list(v.items())[:256]} if depth < 6 else None
    if isinstance(v, (list, tuple)):
        return [_bounded(x, depth + 1, b)
                for x in list(v)[:512]] if depth < 6 else None
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else _clean(v, 32)
    return _clean(v)


def _elements(res, cap: int = ELEMENT_CAP) -> list:
    """ui.elements reply -> [{id,label,rect}] — bounded, sanitized,
    malformed entries dropped (never an exception)."""
    raw = res.get("elements") if isinstance(res, dict) else res
    out = []
    for el in (raw[:cap] if isinstance(raw, list) else []):
        if not isinstance(el, dict):
            continue
        rect = _rect(el.get("rect"))
        if rect is None:
            continue
        el_id = _clean(el.get("id"), ID_CAP)
        if not el_id:
            continue
        out.append({"id": el_id,
                    "label": _clean(el.get("label"), ID_CAP),
                    "rect": rect})
    return out


# ------------------------------------------------------------- the client

class ControlClient:
    """One JSON-lines control connection (loopback only).

    `call()` is one request -> one reply; malformed reply lines are
    skipped and counted (`malformed`) rather than crashing, inside a
    per-call skip cap and an absolute read deadline. A transport
    failure (down/timeout/protocol — the server closes connections on
    protocol violations) reconnects ONCE and retries once; an
    `ok:false` refusal is a real answer and never retried.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9876, *,
                 connect_s: float = CONNECT_S, read_s: float = READ_S,
                 max_line: int = MAX_LINE, max_skip: int = MAX_SKIP,
                 element_cap: int = ELEMENT_CAP):
        host = str(host or "").strip("[]")
        if host.lower() not in _LOOPBACK:
            raise ValueError(f"control host must be loopback, got "
                             f"{host!r}")
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError(f"bad control port {port!r}")
        self.host, self.port = host, port
        self.connect_s = max(0.05, min(float(connect_s), 10.0))
        self.read_s = max(0.1, min(float(read_s), 60.0))
        self.max_line = int(max_line)
        self.max_skip = int(max_skip)
        self.element_cap = int(element_cap)
        self.malformed = 0
        self._sock = None
        self._buf = b""
        self._seq = 0

    # -- lifecycle -------------------------------------------------
    def open(self) -> "ControlClient":
        self.close()
        try:
            s = socket.create_connection((self.host, self.port),
                                         timeout=self.connect_s)
        except socket.timeout:
            raise ControlError("timeout", "connect timed out") from None
        except OSError as e:
            raise ControlError("down", str(e)) from None
        try:
            s.settimeout(self.read_s)
        except OSError:
            pass
        self._sock = s
        self._buf = b""
        return self

    def close(self) -> None:
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def __enter__(self):
        return self.open()

    def __exit__(self, *a):
        self.close()
        return False

    # -- wire ------------------------------------------------------
    def _readline(self, deadline: float):
        """One newline-terminated line -> bytes; None on clean EOF.
        Oversized lines (> max_line) drain to their newline and return
        the _TOO_LONG sentinel; every recv is deadline-bounded so a
        drip-feeding peer cannot stall the turn."""
        over = False
        while True:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                raw, self._buf = self._buf[:nl], self._buf[nl + 1:]
                return _TOO_LONG if over or len(raw) > self.max_line \
                    else raw
            if len(self._buf) > self.max_line:
                over, self._buf = True, b""
            left = deadline - time.monotonic()
            if left <= 0:
                raise ControlError("timeout", "read timed out")
            try:
                self._sock.settimeout(left)
                data = self._sock.recv(65536)
            except socket.timeout:
                raise ControlError("timeout", "read timed out") from None
            except OSError as e:
                raise ControlError("down", str(e)) from None
            if not data:
                if self._buf and not over:
                    raw, self._buf = self._buf, b""
                    return raw          # unterminated tail at EOF
                return None
            self._buf += data

    def _reply(self, deadline: float):
        """Lines -> the reply object. Skips + counts blanks, garbage,
        wrong-id echoes; refuses on ok:false; bounds the whole walk."""
        skipped = 0
        while True:
            raw = self._readline(deadline)
            if raw is None:
                raise ControlError("down", "connection closed")
            ok = False
            if raw is not _TOO_LONG and raw.strip():
                try:
                    obj = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    obj = None
                if isinstance(obj, dict):
                    oid = obj.get("id")
                    known = ("ok" in obj or "result" in obj
                             or "error" in obj)
                    # a reply for a different id is noise on our
                    # dedicated connection — skip it like any other
                    # malformed line
                    ok = known and (oid is None or oid == self._seq)
            if not ok:
                self.malformed += 1
                skipped += 1
                if skipped > self.max_skip:
                    raise ControlError(
                        "protocol", f">{self.max_skip} malformed reply "
                                    "lines")
                continue
            if obj.get("ok") is False or "error" in obj:
                raise ControlError(
                    "refused",
                    _clean(obj.get("error") or "control error", 200))
            return obj.get("result")

    def _call(self, method: str, params: dict | None, read_s: float):
        self._seq += 1
        body = json.dumps({"id": self._seq, "method": method,
                           "params": params or {}},
                          separators=(",", ":"))
        if len(body) > MAX_REQ_BYTES:
            raise ControlError("protocol", "request over size bound")
        try:
            self._sock.sendall(body.encode() + b"\n")
        except (OSError, AttributeError) as e:
            raise ControlError("down", str(e)) from None
        return self._reply(time.monotonic() + read_s)

    def call(self, method: str, params: dict | None = None, *,
             read_s: float | None = None, sanitize=_bounded):
        """One request -> its `result` payload. `sanitize` maps the raw
        wire value to a safe form — _bounded by default; the typed
        helpers pass None and apply their own per-field bounds so a
        generic node budget can't silently truncate an element list."""
        if not _METHOD.match(method or ""):
            raise ValueError(f"bad control method {method!r}")
        wait = self.read_s if read_s is None else max(0.1, float(read_s))
        try:
            if self._sock is None:
                self.open()
            res = self._call(method, params, wait)
            return sanitize(res) if sanitize else res
        except ControlError as e:
            if e.code == "refused":
                raise
            # transport failure: the documented recovery is a fresh
            # connection — retry exactly once; a second failure
            # propagates to the caller (never more than two connects)
            self.open()
            try:
                res = self._call(method, params, wait)
            except ControlError:
                self.close()    # a dead socket isn't worth keeping
                raise
            return sanitize(res) if sanitize else res

    # -- typed helpers ---------------------------------------------
    def elements(self, prefix: str = "") -> list:
        """`ui.elements {prefix?}` -> sanitized [{id,label,rect}]."""
        params = {"prefix": _clean(prefix, 128)} if prefix else None
        return _elements(self.call("ui.elements", params,
                                   sanitize=None), self.element_cap)

    def inspect(self) -> dict:
        """`ui.inspect` -> sanitized UI state dict."""
        res = self.call("ui.inspect")
        return res if isinstance(res, dict) else {}

    def screenshot(self, panel: str = "", path: str = "") -> dict:
        """`ui.screenshot {panel?, path?}` — panel-cropped PNG for the
        U5 dense-observe path. Its own longer read budget (the app
        waits for a presented frame)."""
        params = {}
        if panel:
            params["panel"] = _clean(panel, 128)
        if path:
            params["path"] = _clean(path, 512)
        res = self.call("ui.screenshot", params,
                        read_s=SCREENSHOT_READ_S)
        return res if isinstance(res, dict) else {}

    def click_id(self, element_id: str, **kw) -> dict:
        """`ui.click {id}` — channel-dispatched click. NOT the default
        dispatch lane (pixel dispatch via cua is — the grounding chain
        is what's being trained/measured); kept for drills and the
        `route: control` evidence tag."""
        params = {"id": _clean(element_id, ID_CAP)}
        params.update({k: v for k, v in kw.items()
                       if isinstance(v, (str, int, float, bool))})
        res = self.call("ui.click", params)
        return res if isinstance(res, dict) else {}


# ------------------------------------------------------------- registry

@dataclasses.dataclass(frozen=True)
class Endpoint:
    """app registry key -> where its control channel listens."""
    app: str
    host: str
    port: int
    match: tuple                  # normalized class/title patterns


# FilmCraft: `filmcraft --control 9876`; class ai.storyteller.filmcraft
# and title "FilmCraft" both normalize to contain "filmcraft".
BUILTIN = (
    Endpoint("filmcraft", "127.0.0.1", 9876, ("filmcraft",)),
)


def _norm(s: str) -> str:
    """'FilmCraft — seq' / 'ai.storyteller.filmcraft' -> a flat match
    token (same convention as tools/desktop.py's window scan)."""
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _parse_endpoint(app: str, val) -> Endpoint | None:
    """User registry entry from config. `control.<app> = "host:port"`
    (a scalar under [control]) or a `[control.<app>]` table with
    port + optional host + optional comma `match` patterns."""
    if not _APP_KEY.match(str(app or "")):
        return None
    host, port, match = "127.0.0.1", None, ()
    if isinstance(val, dict):
        host = str(val.get("host") or host)
        port = val.get("port")
        m = val.get("match")
        match = tuple(_norm(p) for p in str(m).split(",") if _norm(p)) \
            if m else ()
    elif isinstance(val, (str, int, float)):
        # "host:port" | ":port" | "port" — rpartition lands the tail
        # in `p` either way (no separator -> p is the whole string)
        h, sep, p = str(val).strip().rpartition(":")
        if sep:
            host = h.strip() or host
        port = p
    if host.strip("[]").lower() not in _LOOPBACK:
        return None             # never let a channel point off-box
    try:
        port = int(str(port).strip())
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None
    return Endpoint(str(app), host, port, match or (_norm(app),))


# [control] keys that are settings, not app endpoints
_SETTING_KEYS = frozenset({
    "connect_timeout_s", "read_timeout_s", "rect_slack_px",
    "element_cap"})


def _config_entries(cfg) -> list:
    out = []
    c = (cfg or {}).get("control")
    if isinstance(c, dict):
        for app, val in c.items():
            if str(app) in _SETTING_KEYS:
                continue
            ep = _parse_endpoint(app, val)
            if ep:
                out.append(ep)
    for sec, tbl in (cfg or {}).items():
        # the flat TOML reader keeps dotted sections as "control.<app>"
        if isinstance(sec, str) and sec.startswith("control.") \
                and isinstance(tbl, dict):
            ep = _parse_endpoint(sec.split(".", 1)[1], tbl)
            if ep:
                out.append(ep)
    return out


class AppControlRegistry:
    """window -> control endpoint. Built-in entries plus the user's
    `control.<app>` keys; a config entry replaces a built-in of the
    same name (e.g. to move FilmCraft's port)."""

    def __init__(self, cfg: dict | None = None):
        self.entries = {ep.app: ep for ep in BUILTIN}
        for ep in _config_entries(cfg):
            self.entries[ep.app] = ep

    def match(self, win: dict | None) -> Endpoint | None:
        """The endpoint for a window dict ({class,title,...}) or None.
        Match = normalized pattern contained in the window's class/
        title (either direction, like the desktop window scan)."""
        if not isinstance(win, dict):
            return None
        hays = [_norm(win.get(k)) for k in
                ("class", "initialClass", "title", "initialTitle")]
        hays = [h for h in hays if h]
        if not hays:
            return None
        best = None
        for ep in self.entries.values():
            for pat in ep.match:
                if not pat:
                    continue
                hit = any(h == pat or (len(pat) >= 3 and len(h) >= 3
                                       and (pat in h or h in pat))
                          for h in hays)
                if hit and (best is None or len(pat) > len(best[0])):
                    best = (pat, ep)       # longest pattern wins ties
        return best[1] if best else None


# -------------------------------------------------- focused window bounds

def _clients():
    from . import verify
    return verify._clients()


def _activewindow():
    from . import hypr
    return hypr.query("activewindow")


def _resolve(v, fn):
    """list|dict|callable|None -> value or None on any failure —
    verify's resolver, kept as a local seam for patching."""
    from . import verify
    return verify._resolve(v, fn)


def _client_bounds(c: dict):
    """(x, y, w, h) logical px from a hypr client dict (`at`/`size` or
    x/y/width/height), or None."""
    if not isinstance(c, dict):
        return None
    at, size = c.get("at"), c.get("size")
    if isinstance(at, (list, tuple)) and isinstance(size, (list, tuple)) \
            and len(at) >= 2 and len(size) >= 2:
        vals = [_num(at[0]), _num(at[1]), _num(size[0]), _num(size[1])]
    else:
        vals = [_num(c.get("x")), _num(c.get("y")),
                _num(c.get("width", c.get("w"))),
                _num(c.get("height", c.get("h")))]
    if any(v is None for v in vals) or vals[2] <= 0 or vals[3] <= 0:
        return None
    return tuple(vals)


def _cua_bounds(cua, win: dict):
    """Bounds via cua `list_windows` — the fallback compositor source
    when the hypr socket can't report them."""
    try:
        listing = cua.list_windows(timeout=0.8)
    except Exception:
        return None
    wins = listing.get("windows") if isinstance(listing, dict) else None
    if not isinstance(wins, list):
        return None
    want = _norm(win.get("title") or win.get("class"))
    pid = win.get("pid")
    for w in wins:
        if not isinstance(w, dict):
            continue
        if pid is not None and w.get("pid") != pid:
            continue
        fb = w.get("frame") or w.get("bounds") or {}
        b = _client_bounds({
            "x": fb.get("x"), "y": fb.get("y"),
            "w": fb.get("width", fb.get("w")),
            "h": fb.get("height", fb.get("h"))})
        if b is None:
            continue
        if pid is not None:
            return b
        have = _norm(w.get("title") or w.get("class"))
        if want and (want in have or have in want):
            return b
    return None


def focused_window(clients=None, active=None, cua=None) -> dict | None:
    """The focused window as {class,title,address,pid,bounds} — class/
    title from `activewindow`, bounds from the compositor client list
    (matched by address, else class), falling back to the activewindow
    payload's own at/size, then a cua `list_windows` frame when given.
    None when no focused window is known; `bounds` may be None (a
    caller that validates rects must check)."""
    aw = _resolve(active, _activewindow)
    if not isinstance(aw, dict):
        return None
    win = {"class": aw.get("class") or "",
           "initialClass": aw.get("initialClass") or "",
           "title": aw.get("title") or "",
           "initialTitle": aw.get("initialTitle") or "",
           "address": aw.get("address") or "",
           "pid": aw.get("pid")}
    if not (win["class"] or win["title"]):
        return None
    listing = _resolve(clients, _clients)
    bounds = None
    if isinstance(listing, list):
        addr = win["address"]
        for c in listing:
            if not isinstance(c, dict):
                continue
            same = (addr and c.get("address") == addr) or \
                (not addr and win["class"]
                 and _norm(c.get("class")) == _norm(win["class"]))
            if same:
                bounds = _client_bounds(c)
                break
    if bounds is None:
        bounds = _client_bounds(aw)          # activewindow has at/size
    if bounds is None and cua is not None:
        bounds = _cua_bounds(cua, win)
    win["bounds"] = bounds
    return win


def channel(cfg: dict | None, win: dict | None = None, **kw):
    """(Endpoint, window) when the focused app ships a channel, else
    None. `win` may be supplied to reuse a caller's own snapshot."""
    win = win if win is not None else focused_window(**kw)
    if win is None:
        return None
    ep = AppControlRegistry(cfg).match(win)
    return (ep, win) if ep else None


# ------------------------------------------------------- rect validation

def _inside(rect, bounds, slack: float) -> bool:
    cx, cy = rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0
    return (bounds[0] - slack <= cx <= bounds[0] + bounds[2] + slack
            and bounds[1] - slack <= cy <= bounds[1] + bounds[3] + slack)


def _win_scale(win: dict, mons) -> float:
    """Scale of the monitor holding the window center, 1.0 when the
    monitor list can't say."""
    b = win.get("bounds")
    if not b or not isinstance(mons, list):
        return 1.0
    cx, cy = b[0] + b[2] / 2.0, b[1] + b[3] / 2.0
    for m in mons:
        if not isinstance(m, dict):
            continue
        s = _num(m.get("scale")) or 1.0
        mw = (_num(m.get("width")) or 0) / s
        mh = (_num(m.get("height")) or 0) / s
        if mw <= 0 or mh <= 0:
            continue
        if m.get("x", 0) <= cx < m.get("x", 0) + mw \
                and m.get("y", 0) <= cy < m.get("y", 0) + mh:
            return s
    return 1.0


def resolve_rect(rect, win: dict, *, ppt=None, mons=None,
                 slack: float = SLACK_PX):
    """Channel element rect -> global logical (x, y, w, h), or None.

    The channel is unauthenticated: a rect is accepted ONLY under an
    interpretation whose center lands inside the app's live compositor
    window bounds. The documented space is window-local egui points
    (rect + window at); a rect that's already global, and both spaces
    corrected by monitor_scale/pixels_per_point when the app reports a
    ppp that differs, are tried in order — first valid wins, none ->
    None (the candidate is dropped, never clicked)."""
    r = _rect(rect)
    bounds = win.get("bounds") if isinstance(win, dict) else None
    if r is None or bounds is None:
        return None
    x, y, w, h = r
    tries = [(bounds[0] + x, bounds[1] + y, w, h),   # window-local pts
             (x, y, w, h)]                          # already global
    p = _num(ppt)
    scale = _win_scale(win, mons)
    if p and p > 0 and scale > 0:
        f = scale / p                                # pt -> logical
        if abs(f - 1.0) > 1e-6:
            tries += [(bounds[0] + x * f, bounds[1] + y * f,
                       w * f, h * f), (x * f, y * f, w * f, h * f)]
    for g in tries:
        if _inside(g, bounds, slack):
            return g
    return None


# -------------------------------------------------- pre-dispatch snapshots
#
# The grounding provider stashes the control state it fetched at aim
# time; the verify rung diffs it against a fresh read after dispatch.
# Keyed by (turn, app): the rung recovers the turn id from the recorded
# turn dir's parent (`rec/<turn>/turn-NNNNN`), falling back to the
# trace context. Bounded — stale entries evict oldest-first. F5: a
# snapshot is single-use (popped on read), carries a monotonic stamp
# the rung compares to the step's aim watermark, and expires on a TTL
# so a previous action's before-state can never serve a later action.

_BEFORE: dict = {}
_BEFORE_TTL_S = 120.0          # a snap this old can only be stale
_BEFORE_GRACE_S = 0.5          # clock-slop slack on the aim watermark


def _turn_id() -> str:
    try:
        from . import trace as _trace
        return _trace.current() or ""
    except Exception:
        return ""


def note_before(turn: str, app: str, inspect: dict, elements: list,
                hit: dict | None = None,
                cap: int = ELEMENT_CAP) -> None:
    """Stash the pre-dispatch channel state for (turn, app). Called by
    the grounding provider on every successful channel read — a
    grounding MISS still records usable before-state for the rung."""
    if not turn or not app:
        return
    _BEFORE[(turn, app)] = {
        "at": time.monotonic(),
        "inspect": inspect if isinstance(inspect, dict) else {},
        # re-normalize: stored rects must be tuples like a fresh
        # after-read, or the element diff reads everything as moved
        "elements": _elements(list(elements or [])[:cap], cap),
        "hit": hit}
    while len(_BEFORE) > PENDING_CAP:
        _BEFORE.pop(next(iter(_BEFORE)))


def _pending(turn: str, app: str, step=None):
    """Pop the pending (turn, app) before-snapshot — single-use, so a
    snapshot can never be served to two verifies. Returns None when no
    snap exists, when it aged past _BEFORE_TTL_S, or when it predates
    the step's `aim_mono` watermark (F5: a snap stashed for an earlier
    action is not this action's before-state)."""
    snap = _BEFORE.pop((turn, app), None)
    if snap is None:
        snap = _BEFORE.pop((_turn_id(), app), None)
    if snap is None:
        return None
    at = snap.get("at")
    if at is None or time.monotonic() - at > _BEFORE_TTL_S:
        return None             # expired — never serve stale state
    aim = (step or {}).get("aim_mono")
    if aim is not None and at < aim - _BEFORE_GRACE_S:
        return None             # belongs to an earlier dispatch
    return snap


# ------------------------------------------------------------- the rung

def _abstain(detail: str) -> dict:
    from . import verify
    return verify._abstain(detail)


def _flat(v, prefix: str = "", out: dict | None = None,
          depth: int = 0) -> dict:
    """inspect dict -> {dotted.key: scalar} — bounded, volatile-free
    comparison input. Lists fold to a `list[N]` shape marker (element
    diffs go through the id-set walk instead)."""
    if out is None:
        out = {}
    if len(out) >= FLAT_CAP or depth > 6:
        return out
    if isinstance(v, dict):
        for k, val in list(v.items())[:128]:
            key = f"{prefix}.{k}" if prefix else str(k)
            _flat(val, key, out, depth + 1)
    elif isinstance(v, (list, tuple)):
        out[prefix] = f"list[{len(v)}]"
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        out[prefix] = v if math.isfinite(v) else "nan"
    else:
        out[prefix] = v
    return out


def _ids(elements) -> dict:
    return {e["id"]: e for e in elements or []
            if isinstance(e, dict) and e.get("id")}


def _diff_vote(before: dict, after: dict) -> dict:
    """landed when the app's reported state visibly moved, missed when
    it is identical — symmetric and never sole-sourcing (R2a; the
    ladder reconciles)."""
    changed = []
    fb, fa = _flat(before.get("inspect")), _flat(after.get("inspect"))
    for k in sorted(set(fb) | set(fa)):
        leaf = str(k).rsplit(".", 1)[-1].lower()
        if leaf in _VOLATILE:
            continue
        if fb.get(k, _MISSING) != fa.get(k, _MISSING):
            changed.append(str(k))
    be, ae = _ids(before.get("elements")), _ids(after.get("elements"))
    added = sorted(set(ae) - set(be))
    gone = sorted(set(be) - set(ae))
    moved = sorted(e for e in set(be) & set(ae)
                   if be[e].get("rect") != ae[e].get("rect"))
    if added:
        changed.append(f"+{len(added)} elements ({','.join(added[:3])})")
    if gone:
        changed.append(f"-{len(gone)} elements ({','.join(gone[:3])})")
    if moved:
        changed.append(f"~{len(moved)} moved ({','.join(moved[:3])})")
    if changed:
        return {"vote": "landed",
                "detail": _clean("; ".join(changed[:8]), 200)}
    return {"vote": "missed",
            "detail": "ui.inspect/elements identical"}


def _write_json(path: pathlib.Path, obj) -> None:
    """Bounded sanitized evidence JSON into the action dir."""
    try:
        text = json.dumps(_bounded(obj), ensure_ascii=False,
                          separators=(",", ":"))
        path.write_text(text[:EVIDENCE_CAP])
    except (OSError, ValueError, TypeError):
        pass


def verify_rung(ctx) -> dict:
    """The "control" verify rung (registered via register()): diff the
    ui.inspect/ui.elements snapshot stashed at aim time against a fresh
    read. Abstains on every failure shape — no channel for the focused
    app, no pending snapshot, channel down, garbage replies — the rung
    corroborates and never blocks the turn."""
    try:
        tdir = pathlib.Path(str(ctx.turn_dir))
    except Exception:
        return _abstain("no turn dir")
    ch = channel(getattr(ctx, "cfg", None))
    if ch is None:
        return _abstain("no control channel for the focused app")
    ep, _win = ch
    snap = _pending(tdir.parent.name, ep.app,
                    step=getattr(ctx, "step", None))
    if snap is None:
        return _abstain("no pre-dispatch snapshot")
    st = settings(getattr(ctx, "cfg", None))
    try:
        with ControlClient(ep.host, ep.port,
                           connect_s=min(st["connect_s"], 1.0),
                           read_s=st["read_s"],
                           element_cap=st["element_cap"]) as c:
            after = {"inspect": c.inspect(), "elements": c.elements()}
    except ControlError as e:
        return _abstain(f"channel {e.code}: {_clean(e)[:80]}")
    except Exception as e:
        return _abstain(f"channel error: {_clean(e)[:80]}")
    # the diff evidence lands in the recorded action dir (the pack
    # picks it up): both snapshots, sanitized and size-bounded
    _write_json(tdir / "control_before.json",
                {"inspect": snap["inspect"], "elements": snap["elements"],
                 "hit": snap.get("hit")})
    _write_json(tdir / "control_after.json", after)
    return _diff_vote(snap, after)


def _f(v, default: float) -> float:
    try:
        r = float(v)
    except (TypeError, ValueError):
        return default
    return r if math.isfinite(r) else default


def settings(cfg: dict | None) -> dict:
    c = (cfg or {}).get("control") or {}
    if not isinstance(c, dict):
        c = {}
    return {
        "connect_s": min(max(_f(c.get("connect_timeout_s"),
                             CONNECT_S), 0.05), 10.0),
        "read_s": min(max(_f(c.get("read_timeout_s"), READ_S), 0.1),
                      60.0),
        "slack_px": _f(c.get("rect_slack_px"), SLACK_PX),
        "element_cap": int(_f(c.get("element_cap"), ELEMENT_CAP)),
    }


def register() -> None:
    """Plug the control diff into verify's rung registry. Called on
    import; verify stays usable without it (unregistered = abstains by
    absence)."""
    try:
        from . import verify
        verify.register_rung("control", verify_rung)
    except Exception:
        pass


register()
