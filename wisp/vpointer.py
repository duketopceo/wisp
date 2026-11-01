"""Instance-scoped input for the isolated test session (KTD6, R5).

Two jobs, both stdlib-only:

  * `is_isolated(cfg)` / `UinputRefused` / `isolated_env()` — the
    run-copy switch `[dev] isolated_session` and the typed refusal every
    uinput path (ydotool clicks, keys, scroll, the typing fallback)
    raises when it is on. uinput devices belong to the whole seat, so an
    isolated run must never reach one: it is refused, never silently
    used.
  * `VirtualPointer` — a minimal Wayland wire-protocol client for
    `zwlr_virtual_pointer_v1`. It talks to the socket named by
    `WAYLAND_DISPLAY` (the isolated instance's, never guessed) and so
    moves, clicks and scrolls only inside that compositor. No package is
    needed: the wire format is a handful of 32-bit words.

Wire format (native endian): every message is `object_id:u32`,
`(size << 16 | opcode):u32`, then the arguments padded to 4 bytes.
Strings are `len:u32` (with the NUL) + bytes + padding; fixed-point
values are 24.8 signed.
"""
import os
import socket
import struct
import time

# -- the isolation switch ---------------------------------------------------


class UinputRefused(RuntimeError):
    """An isolated-session run asked for an input path that could reach
    the live seat (uinput, the cua daemon, a live hyprctl cursor)."""


def is_isolated(cfg) -> bool:
    return str(((cfg or {}).get("dev") or {}).get("isolated_session", "")
               ).lower() == "true"


def refuse(what: str):
    raise UinputRefused(
        f"isolated session: {what} is refused (uinput reaches the live "
        "seat); input goes through the instance's virtual pointer / wtype")


def isolated_env(base=None) -> dict:
    """The environment for a spawned input tool in an isolated run: the
    process env without `DISPLAY`, and with an explicit instance
    `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR`. Nothing is guessed from
    /run/user — a missing value is a refusal, not a fallback to the live
    socket."""
    env = dict(os.environ if base is None else base)
    env.pop("DISPLAY", None)
    for k in ("WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"):
        if not env.get(k):
            raise UinputRefused(
                f"isolated session: {k} is not set; start the session "
                "with scripts/isolated_session.py start and source its "
                "env file")
    return env


# -- the wire client ----------------------------------------------------------

BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
AXIS_VERTICAL = 0
AXIS_HORIZONTAL = 1
AXIS_SOURCE_WHEEL = 0

_DISPLAY = 1            # wl_display is always object 1
_TIMEOUT_S = 3.0
_MANAGER = "zwlr_virtual_pointer_manager_v1"
_SEAT = "wl_seat"


class VPointerError(RuntimeError):
    pass


def _pad(n: int) -> int:
    return (n + 3) & ~3


def _str(s: str) -> bytes:
    b = s.encode() + b"\0"
    return struct.pack("=I", len(b)) + b + b"\0" * (_pad(len(b)) - len(b))


def _fixed(v: float) -> int:
    return int(round(v * 256))


def _msg(obj: int, opcode: int, args: bytes = b"") -> bytes:
    return struct.pack("=II", obj, ((8 + len(args)) << 16) | opcode) + args


def _u(*vals) -> bytes:
    return struct.pack("=" + "I" * len(vals), *vals)


def _now_ms() -> int:
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


def socket_path(env=None) -> str:
    env = os.environ if env is None else env
    wd = env.get("WAYLAND_DISPLAY") or ""
    if not wd:
        raise VPointerError("WAYLAND_DISPLAY is not set")
    if os.path.isabs(wd):
        return wd
    rd = env.get("XDG_RUNTIME_DIR") or ""
    if not rd:
        raise VPointerError("XDG_RUNTIME_DIR is not set")
    return os.path.join(rd, wd)


class VirtualPointer:
    """One `zwlr_virtual_pointer_v1` on the compositor at `path`.

    Object ids: 1 wl_display, 2 wl_registry, 3 first sync callback; the
    rest are allocated in order.
    """

    def __init__(self, path: str | None = None, env=None,
                 timeout_s: float = _TIMEOUT_S):
        self.path = path or socket_path(env)
        self.timeout_s = timeout_s
        self._sock = None
        self._next = 2
        self._buf = b""
        self._globals = {}
        self._ptr = 0

    # -- plumbing ------------------------------------------------------
    def _new_id(self) -> int:
        self._next += 1
        return self._next

    def _send(self, data: bytes) -> None:
        try:
            self._sock.sendall(data)
        except OSError as e:
            # the compositor may have closed on a protocol error it had
            # already written to us: surface that instead of the EPIPE
            why = self._pending_error()
            raise VPointerError(why or f"send failed: {e}") from e

    def _pending_error(self) -> str:
        try:
            self._sock.settimeout(0.5)
            while True:
                obj, op, body = self._event()
                if obj == _DISPLAY and op == 0:
                    return self._error_text(body)
        except (VPointerError, OSError, struct.error):
            return ""

    @staticmethod
    def _error_text(body: bytes) -> str:
        oid, code = struct.unpack_from("=II", body)
        (ln,) = struct.unpack_from("=I", body, 8)
        text = body[12:12 + ln - 1].decode("utf-8", "replace")
        return f"protocol error on object {oid} (code {code}): {text}"

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            try:
                chunk = self._sock.recv(65536)
            except (OSError, socket.timeout) as e:
                raise VPointerError(f"compositor did not answer: {e}") from e
            if not chunk:
                raise VPointerError("compositor closed the connection")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _event(self) -> tuple:
        obj, word = struct.unpack("=II", self._recv_exact(8))
        size, opcode = word >> 16, word & 0xFFFF
        return obj, opcode, self._recv_exact(size - 8)

    def _roundtrip(self) -> None:
        """wl_display.sync, then read until its callback fires; global
        events and protocol errors are handled on the way."""
        cb = self._new_id()
        self._send(_msg(_DISPLAY, 0, _u(cb)))
        while True:
            obj, op, body = self._event()
            if obj == _DISPLAY and op == 0:              # error
                raise VPointerError(self._error_text(body))
            if obj == 2 and op == 0:                     # registry.global
                name, ln = struct.unpack_from("=II", body)
                iface = body[8:8 + ln - 1].decode()
                (ver,) = struct.unpack_from("=I", body, 8 + _pad(ln))
                self._globals[iface] = (name, ver)
            elif obj == cb and op == 0:                  # callback.done
                return

    # -- lifecycle -----------------------------------------------------
    def connect(self) -> "VirtualPointer":
        try:
            return self._connect()
        except BaseException:
            self.close()
            raise

    def _connect(self) -> "VirtualPointer":
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout_s)
        try:
            s.connect(self.path)
        except OSError as e:
            s.close()
            raise VPointerError(
                f"cannot connect to {self.path}: {e}") from e
        self._sock = s
        self._send(_msg(_DISPLAY, 1, _u(2)))             # get_registry(2)
        self._roundtrip()
        for iface in (_SEAT, _MANAGER):
            if iface not in self._globals:
                raise VPointerError(
                    f"compositor does not offer {iface}")
        seat = self._bind(_SEAT, 1)
        mgr = self._bind(_MANAGER, 1)
        self._ptr = self._new_id()
        # create_virtual_pointer(seat, new_id)
        self._send(_msg(mgr, 0, _u(seat, self._ptr)))
        self._roundtrip()
        return self

    def _bind(self, iface: str, want_ver: int) -> int:
        name, ver = self._globals[iface]
        v = min(ver, want_ver)
        oid = self._new_id()
        # registry.bind: name, then the untyped new_id = interface
        # string + version + id
        self._send(_msg(2, 0, _u(name) + _str(iface) + _u(v, oid)))
        return oid

    def close(self) -> None:
        s, self._sock = self._sock, None
        if s is not None:
            try:
                if self._ptr:
                    s.sendall(_msg(self._ptr, 8))        # destroy
            except OSError:
                pass
            s.close()

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- requests ------------------------------------------------------
    def motion_absolute(self, x: int, y: int, x_extent: int,
                        y_extent: int) -> None:
        self._send(_msg(self._ptr, 1, _u(
            _now_ms(), int(x), int(y), int(x_extent), int(y_extent))))
        self._frame()

    def button(self, code: int = BTN_LEFT, pressed: bool = True) -> None:
        self._send(_msg(self._ptr, 2, _u(
            _now_ms(), int(code), 1 if pressed else 0)))
        self._frame()

    def axis(self, value: float, axis: int = AXIS_VERTICAL,
             discrete: int = 0) -> None:
        """One scroll step: wheel source, `value` in px (positive scrolls
        down/right), `discrete` wheel detents."""
        t = _now_ms()
        self._send(_msg(self._ptr, 5, _u(AXIS_SOURCE_WHEEL)))
        if discrete:
            self._send(_msg(self._ptr, 7, struct.pack(
                "=IIii", t, axis, _fixed(value), int(discrete))))
        else:
            self._send(_msg(self._ptr, 3, struct.pack(
                "=IIi", t, axis, _fixed(value))))
        self._frame()

    def _frame(self) -> None:
        self._send(_msg(self._ptr, 4))

    def flush(self) -> None:
        """Round-trip so the compositor has consumed every request (and
        any protocol error surfaces) before the caller moves on."""
        self._roundtrip()


# -- one-shot helpers (each opens, acts, round-trips, closes) ----------------

def _norm(x, y, extent, origin):
    ox, oy = origin
    return int(x) - int(ox), int(y) - int(oy)


def move(x: int, y: int, extent: tuple, origin=(0, 0), env=None,
         path: str | None = None) -> None:
    """Move the instance cursor to logical (x, y). `extent` = (w, h) of
    the layout's logical bounding box whose top-left is `origin`."""
    px, py = _norm(x, y, extent, origin)
    with VirtualPointer(path, env) as vp:
        vp.motion_absolute(px, py, int(extent[0]), int(extent[1]))
        vp.flush()


def click(x: int, y: int, extent: tuple, origin=(0, 0), env=None,
          path: str | None = None, button: int = BTN_LEFT) -> None:
    px, py = _norm(x, y, extent, origin)
    with VirtualPointer(path, env) as vp:
        vp.motion_absolute(px, py, int(extent[0]), int(extent[1]))
        vp.button(button, True)
        vp.button(button, False)
        vp.flush()


def scroll(dx: float = 0, dy: float = 0, env=None,
           path: str | None = None, step: float = 60.0) -> None:
    """Scroll by (dx, dy) px, in wheel-sized steps (positive = down /
    right)."""
    with VirtualPointer(path, env) as vp:
        for axis, total in ((AXIS_VERTICAL, dy), (AXIS_HORIZONTAL, dx)):
            left = float(total)
            while abs(left) >= 1:
                part = max(-step, min(step, left))
                vp.axis(part, axis, discrete=1 if part > 0 else -1)
                left -= part
        vp.flush()
