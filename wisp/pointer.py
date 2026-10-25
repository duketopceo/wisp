"""Pointer backend registry (W8).

One `Backend` per injector, in auto order: cua (zwlr_virtual_pointer —
clicks ride a separate agent cursor, no real-pointer move, no focus
steal; `move_cursor(scope:"desktop")` DOES drive the real OS pointer)
> hyprcursor (Hyprland cursor move + ydotool click) > ydotool > wlrctl
> guide (never drives; the ghost cursor shows the target and the user
clicks). U5: every dispatch reports the delivery it actually used —
`backend_delivery` in wisp/delivery.py is the truth table — and any
real-pointer dispatch arms the realinput yield watch so user input
takes the pointer back mid-call. `Registry(cfg).select()` returns the
backend that `[pointer] backend` resolves to:

  auto (default, or any unknown value)  first available in auto order
  <name>                                that backend only; unavailable
                                        means None (no silent fallthrough)
  none                                  None (guide mode)
  exclude=(...)                         fallback lookup: names skipped,
                                        the pin ignored, auto order

Rules carried from W1, unchanged:
  * move is idempotent and falls through: a failed cua move tries the
    Hyprland socket eval (on Hyprland), then the next backend in auto
    order. A non-cua move on Hyprland goes over the socket eval first.
  * a click is NEVER retried on another backend (double-click risk): a
    failed click is reported and the act loop re-observes.
  * a cancelled turn raises `cancel.Cancelled` before any call and
    mid-call; it is never a failure to fall back from.

Coordinates are logical Hyprland desktop coordinates (the `desktop`
frame cua is told); no backend rescales them.
"""
import dataclasses
import subprocess

from . import cancel as _cancel
from . import cua as _cua
from . import delivery as _delivery
from . import hypr
from . import platform
from . import realinput

NAMES = ("cua", "hyprcursor", "ydotool", "wlrctl", "guide")
_ARGV_TIMEOUT_S = 10


@dataclasses.dataclass(frozen=True)
class Outcome:
    ok: bool
    backend: str | None = None   # who performed (or last attempted) it
    error: str = ""              # cua_code or short reason when not ok
    delivery: str = ""           # "background"|"pointer"|"guide" (U5)


class Backend:
    name = ""
    capabilities: frozenset = frozenset()
    coordinate_space = "logical"
    drives = True

    def available(self) -> bool:
        raise NotImplementedError

    def health(self) -> dict:
        ok = self.available()
        return {"name": self.name, "ok": ok,
                "detail": "" if ok else self.unavailable_hint()}

    def unavailable_hint(self) -> str:
        return f"{self.name} not available"

    def move(self, x: int, y: int) -> bool:
        return False

    def click(self, x: int, y: int) -> bool:
        return False

    def scroll(self, dx: int, dy: int) -> bool:
        return False

    def cancel(self) -> None:
        """In-flight calls die with the turn's CancelToken (it kills
        the child process group); nothing is held between calls."""


class CuaBackend(Backend):
    name = "cua"
    # "background" holds for CLICK only (virtual-pointer clicks never
    # move the user cursor); move_cursor(scope:"desktop") is a
    # real-pointer drive — see delivery.backend_delivery.
    capabilities = frozenset({"background", "no_focus_steal"})
    coordinate_space = "desktop"

    def __init__(self, client: _cua.Cua | None = None,
                 timeout_s: float = _cua.CLICK_TIMEOUT_S):
        self._client = client
        self._timeout_s = timeout_s
        self.last_error = ""

    @property
    def client(self) -> _cua.Cua:
        if self._client is None:
            from .pipeline import hypr_env
            self._client = _cua.Cua(timeout_s=self._timeout_s,
                                    env=hypr_env())
        return self._client

    def available(self) -> bool:
        return bool(platform._cua_live())

    def unavailable_hint(self) -> str:
        return "cua-driver not on PATH or its socket is missing"

    def _do(self, fn, x, y, **kw) -> bool:
        self.last_error = ""
        try:
            fn(x, y, **kw)
            return True
        except _cua.CuaError as e:
            self.last_error = e.cua_code
            return False

    # every cua-bound dispatch carries the stable "wisp" session label
    # (U1 — session-filtered turn recording attributes by it)
    def move(self, x, y) -> bool:
        return self._do(self.client.move_cursor, x, y,
                        session=_cua.SESSION)

    def click(self, x, y) -> bool:
        return self._do(self.client.click, x, y, session=_cua.SESSION)


def _run_argv(cmds: list) -> bool:
    from .pipeline import hypr_env
    for c in cmds:
        realinput.check()   # a human grabbed the pointer mid-sequence
        try:
            r = _cancel.run(c, capture_output=True, env=hypr_env(),
                            timeout=_ARGV_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return False
        if r.returncode != 0:
            return False
    return True


class ArgvBackend(Backend):
    def move(self, x, y) -> bool:
        return _run_argv(platform.pointer_cmds(x, y, self.name,
                                               click=False))

    def click(self, x, y) -> bool:
        return _run_argv(platform.pointer_cmds(x, y, self.name,
                                               click=True))


class HyprcursorBackend(ArgvBackend):
    name = "hyprcursor"

    def available(self) -> bool:
        return bool(platform._which("hyprctl") and platform._which("ydotool"))

    def unavailable_hint(self) -> str:
        return "needs hyprctl and ydotool"


class YdotoolBackend(ArgvBackend):
    name = "ydotool"
    capabilities = frozenset({"scroll"})

    def available(self) -> bool:
        return bool(platform._which("ydotool"))

    def scroll(self, dx, dy) -> bool:
        return _run_argv([["ydotool", "mousemove", "--wheel",
                           "-x", str(int(dx)), "-y", str(int(dy))]])


class WlrctlBackend(ArgvBackend):
    name = "wlrctl"

    def available(self) -> bool:
        return bool(platform._which("wlrctl"))


class GuideBackend(Backend):
    name = "guide"
    drives = False

    def available(self) -> bool:
        return True


class Registry:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        self._b = {b.name: b for b in (
            CuaBackend(timeout_s=self._cua_timeout()), HyprcursorBackend(), YdotoolBackend(),
            WlrctlBackend(), GuideBackend())}

    def _cua_timeout(self) -> float:
        try:
            ms = float((self.cfg.get("cua", {}) or {}).get(
                "timeout_ms", _cua.CLICK_TIMEOUT_S * 1000))
        except (TypeError, ValueError):
            ms = _cua.CLICK_TIMEOUT_S * 1000
        return min(max(ms, 100.0), 10000.0) / 1000.0

    def names(self) -> list:
        return list(self._b)

    def get(self, name: str) -> Backend:
        return self._b[name]

    @property
    def pin(self) -> str:
        return (self.cfg.get("pointer", {}) or {}).get("backend", "auto")

    def select(self, exclude: tuple = ()) -> Backend | None:
        """The driving backend to use, or None (guide mode)."""
        auto = [b for b in self._b.values() if b.drives]
        if platform.current() != "linux":
            # hyprcursor/ydotool/wlrctl are Linux injectors; off-Linux
            # only cua-driver is eligible, else guide mode (None).
            cua = self._b["cua"]
            if exclude and "cua" in exclude:
                return None
            want = self.pin
            if want == "none":
                return None
            if want in self._b and self._b[want].drives:
                return self._b[want] if self._b[want].available() else None
            return cua if cua.available() else None
        if exclude:
            return next((b for b in auto
                         if b.name not in exclude and b.available()), None)
        want = self.pin
        if want in self._b and self._b[want].drives:
            b = self._b[want]
            return b if b.available() else None
        if want == "none":
            return None
        return next((b for b in auto if b.available()), None)

    # -- actions -------------------------------------------------------
    def _pick(self, name: str | None) -> Backend | None:
        """`name` = a backend already resolved by the caller (platform
        shim); otherwise resolve from cfg."""
        if name:
            b = self._b.get(name)
            return b if b is not None and b.drives else None
        return self.select()

    def move(self, x: int, y: int, backend: str | None = None) -> Outcome:
        _cancel.check(); realinput.check()
        b = self._pick(backend)
        if b is None:
            return Outcome(False, None, "no_backend", "guide")
        # every move path drives the real cursor (cua's scope:desktop
        # move included) — arm the yield watch before touching it
        realinput.arm()
        if b.name == "cua":
            if b.move(x, y):
                realinput.expect(x, y)
                return Outcome(True, "cua", delivery="pointer")
            err = b.last_error
            _cancel.check(); realinput.check()
            return self._move_fallback(x, y, err)
        if platform.uses_hypr() and hypr.run_lua(hypr.cursor_move(x, y)):
            realinput.expect(x, y)
            return Outcome(True, "hypr", delivery="pointer")
        _cancel.check(); realinput.check()
        ok = b.move(x, y)
        if ok:
            realinput.expect(x, y)
        return Outcome(ok, b.name, delivery="pointer")

    def _move_fallback(self, x, y, err: str) -> Outcome:
        """cua move failed: hypr eval (on Hyprland), then the next
        backend in auto order."""
        if platform.uses_hypr() and hypr.run_lua(hypr.cursor_move(x, y)):
            realinput.expect(x, y)
            return Outcome(True, "hypr", delivery="pointer")
        _cancel.check(); realinput.check()
        nxt = self.select(exclude=("cua",))
        if nxt is not None and nxt.move(x, y):
            realinput.expect(x, y)
            return Outcome(True, nxt.name, delivery="pointer")
        return Outcome(False, nxt.name if nxt else "cua", err, "pointer")

    def click(self, x: int, y: int, backend: str | None = None) -> Outcome:
        _cancel.check(); realinput.check()
        b = self._pick(backend)
        if b is None:
            return Outcome(False, None, "no_backend", "guide")
        d = _delivery.backend_delivery(b.name, "click")
        if d == "pointer":
            realinput.arm()
        ok = b.click(x, y)
        if ok and d == "pointer":
            realinput.expect(x, y)
        return Outcome(ok, b.name,
                       "" if ok else getattr(b, "last_error", "")
                       or "click_failed", d)

    def scroll(self, dx: int, dy: int) -> Outcome:
        _cancel.check(); realinput.check()
        b = self.select()
        if b is None or "scroll" not in b.capabilities:
            return Outcome(False, b.name if b else None, "unsupported",
                           "guide" if b is None else "background")
        # wheel scrolls inject axis events at the focused surface —
        # the pointer never moves
        return Outcome(b.scroll(dx, dy), b.name, delivery="background")

    def health(self) -> list:
        return [b.health() for b in self._b.values()]


def registry(cfg: dict | None = None) -> Registry:
    return Registry(cfg)
