"""Real-input yield watch (U5, R12): exclusive drive with instant
takeover — while the act loop drives the REAL pointer (delivery
`pointer`), input from a physical device must win immediately.

Two sensing paths, picked once for the process:

  evdev — read /dev/input/event* directly (stdlib only). The agent's
          own injectors are filtered out by device name (ydotoold's
          uinput device; wtype/cua/wlrctl ride compositor-side
          protocols and never appear here), so a synthetic stream
          cannot trip the watch.
  drift — no evdev access (the stock case: /dev/input is root:input
          and wispd runs unprivileged): poll the real cursor position;
          movement beyond DRIFT_PX that the drive did not command means
          a human took the mouse.
  off   — neither path available: the yield falls back to the normal
          interrupt path (Esc / `wispd interrupt`); docs/CUA.md says so.

The watch only flags once `arm()` has run — i.e. only after the loop
actually dispatched a real-pointer op — so background-only runs (DOM
clicks, typing, cua virtual-pointer clicks) never yield on the user's
own input. `begin()` resets per act run; `check()` raises
`cancel.Cancelled`, the same unwind as a user interrupt.
"""
import os
import re
import selectors
import threading
from pathlib import Path

import fcntl

from . import cancel as _cancel
from . import delivery as _delivery

INPUT_DIR = "/dev/input"
DRIFT_PX = 32
POLL_S = 0.1

_EVENT_RE = re.compile(r"^event\d+$")
# names of synthetic/virtual input sources — our own stream and every
# known injector, filtered out of the evdev watch
VIRTUAL_NAME = re.compile(
    r"ydotool|uinput|virtual|wisp|cua|wlrctl|wtype|xdotool|xtest|"
    r"qemu|vbox|vmware|parallels", re.I)
# EVIOCGNAME(256): _IOC(_IOC_READ, 'E', 0x06, 256)
_EVIOCGNAME = (2 << 30) | (256 << 16) | (ord("E") << 8) | 0x06


def _device_name(fd) -> str:
    if fcntl is None:
        return ""
    try:
        raw = fcntl.ioctl(fd, _EVIOCGNAME, bytes(256))
    except OSError:
        return ""
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def real_devices(input_dir: str = INPUT_DIR) -> list:
    """Open every readable real (non-virtual) evdev device."""
    fds = []
    try:
        entries = os.listdir(input_dir)
    except OSError:
        return fds
    for e in sorted(entries):
        if not _EVENT_RE.match(e):
            continue
        try:
            fd = os.open(Path(input_dir) / e,
                         os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        if VIRTUAL_NAME.search(_device_name(fd)):
            os.close(fd)
            continue
        fds.append(fd)
    return fds


def _hypr_cursor_pos():
    """Real cursor position via the Hyprland socket, or None."""
    try:
        from . import hypr
        p = hypr.query("cursorpos")
        return int(p["x"]), int(p["y"])
    except (ImportError, RuntimeError, KeyError, TypeError, ValueError):
        return None


class Watch:
    """One sensing thread for the process. `devices=None` enumerates
    /dev/input; a caller may inject fd-like objects (tests pass pipe
    ends) — bytes on any of them count as real input once armed.
    `cursor_pos` is injectable for the drift path."""

    def __init__(self, input_dir: str = INPUT_DIR, devices=None,
                 cursor_pos=None, poll_s: float = POLL_S,
                 drift_px: int = DRIFT_PX):
        self._dir = input_dir
        self._devices = devices
        self._cursor_pos = cursor_pos or _hypr_cursor_pos
        self._poll_s = poll_s
        self._drift_px = drift_px
        self._armed = threading.Event()
        self._yield = threading.Event()
        self._expected = None
        self._stop = threading.Event()
        self._thread = None
        self._fds = []
        self.mode = "off"

    # -- lifecycle -----------------------------------------------------
    def start(self) -> str:
        """Pick a sensing path; returns the mode ("evdev"|"drift"|"off")."""
        fds = self._devices if self._devices is not None \
            else real_devices(self._dir)
        if fds:
            self._fds = list(fds)
            for fd in self._fds:
                try:
                    os.set_blocking(fd, False)   # injected fds may block
                except OSError:
                    pass
            self._thread = threading.Thread(target=self._evdev_loop,
                                            daemon=True)
            mode = "evdev"
        else:
            # degrade: only stay live when the cursor can be read
            mode = "drift" if self._cursor_pos() is not None else "off"
            if mode == "off":
                return mode
            self._thread = threading.Thread(target=self._drift_loop,
                                            daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            return "off"
        # publish mode only after the reader is actually alive — a dead
        # thread must not masquerade as a live watch
        self.mode = mode
        return mode

    def begin(self) -> None:
        """Per-run reset: disarm, drain any input backlog buffered
        before the arm (a stale event must not yield a fresh run), then
        clear yielded/expected."""
        self._armed.clear()
        for fd in self._fds:
            try:
                while os.read(fd, 4096):
                    pass
            except (BlockingIOError, OSError):
                pass
        self._yield.clear()
        self._expected = None

    def finish(self) -> None:
        """Run over: disarm and drop a pending yield so real input that
        lands while the daemon is idle cannot poison the next run (or a
        non-loop dispatch that never began a watch)."""
        self._armed.clear()
        self._yield.clear()
        self._expected = None

    def close(self) -> None:
        self._stop.set()
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds = []
        if self._thread is not None:
            self._thread.join(timeout=1)

    # -- the drive's side ----------------------------------------------
    def arm(self) -> None:
        """A real-pointer dispatch is about to run (or just did)."""
        self._armed.set()

    def expect(self, x, y) -> None:
        """The drive commanded the cursor to (x,y) — the drift baseline."""
        self._armed.set()
        try:
            self._expected = (int(x), int(y))
        except (TypeError, ValueError):
            pass

    def yielded(self) -> bool:
        return self._yield.is_set()

    def check(self) -> None:
        """Raise Cancelled when real input took the pointer — only
        while a dispatch context is armed; a yield flag left by a dead
        or finished run is ignored (begin()/finish() clear it anyway)."""
        if self._armed.is_set() and self._yield.is_set():
            raise _cancel.Cancelled("real input took the pointer")

    # -- sensing --------------------------------------------------------
    def _evdev_loop(self) -> None:
        sel = selectors.DefaultSelector()
        try:
            for fd in self._fds:
                sel.register(fd, selectors.EVENT_READ)
            while not self._stop.is_set():
                for key, _ev in sel.select(0.2):
                    # a dead fd (unplugged device, closed pipe) reports
                    # ready every pass — drop it or select spins forever
                    try:
                        dead = not os.read(key.fd, 4096)
                    except OSError:
                        dead = True
                    if dead:
                        try:
                            sel.unregister(key.fd)
                        except (KeyError, ValueError):
                            pass
                        try:
                            os.close(key.fd)
                        except OSError:
                            pass
                        if key.fd in self._fds:
                            self._fds.remove(key.fd)
                        if not self._fds:
                            self.mode = "off"
                            return
                        continue
                    if self._armed.is_set():
                        # flag it and keep reading — the thread is the
                        # only sensor; it must outlive the yield
                        self._yield.set()
        except Exception:
            self.mode = "off"   # dead reader must not claim a live watch
        finally:
            sel.close()

    def _drift_loop(self) -> None:
        try:
            while not self._stop.is_set():
                # sleep while nothing is driving; poll while armed
                if not self._armed.is_set():
                    self._armed.wait(0.5)
                    continue
                exp = self._expected
                if exp is not None:
                    pos = self._cursor_pos()
                    if pos is not None and (
                            abs(pos[0] - exp[0]) > self._drift_px
                            or abs(pos[1] - exp[1]) > self._drift_px):
                        # flag it and keep polling — the thread is the
                        # only sensor; it must outlive the yield
                        self._yield.set()
                self._stop.wait(self._poll_s)
        except Exception:
            self.mode = "off"


# -- process-level watch ------------------------------------------------
# One Watch for the daemon's lifetime: evdev fds are a fixed handful,
# the reader thread idles on select. The act loop calls begin() per run
# so flags never leak across turns; the pointer registry calls
# arm()/expect()/check() around real dispatches — all no-ops before the
# first drive-capable run (and after _stop_for_test()).
_LOCK = threading.Lock()
_WATCH: Watch | None = None


def _create() -> Watch:
    w = Watch()
    w.start()
    return w


def _watch() -> Watch | None:
    global _WATCH
    with _LOCK:
        if _WATCH is None:
            _WATCH = _create()
    return _WATCH


def _drive_possible(cfg: dict | None) -> bool:
    """Could this run touch the real cursor? DOM runs and
    background-policy runs never do; guide mode injects nothing."""
    c = cfg or {}
    if (c.get("screen") or {}).get("dom_page"):
        return False
    if (c.get("pointer") or {}).get("mode") != "drive":
        return False
    return _delivery.mode(c) != "background"


def begin(cfg: dict | None) -> str:
    """Reset the watch for a new act run; returns its mode
    ("evdev"|"drift"|"off") so the run can log the active mechanism.
    Never raises — a watch failure must not break a turn."""
    try:
        if _WATCH is not None:
            _WATCH.begin()
        if not _drive_possible(cfg):
            return "off"
        return _watch().mode
    except Exception:
        return "off"


def arm() -> None:
    w = _WATCH
    if w is not None:
        w.arm()


def expect(x, y) -> None:
    w = _WATCH
    if w is not None:
        w.expect(x, y)


def check() -> None:
    w = _WATCH
    if w is not None:
        w.check()


def yielded() -> bool:
    w = _WATCH
    return w is not None and w.yielded()


def finish() -> None:
    """End-of-run cleanup: the act loop calls this in a finally so the
    armed state never outlives the turn it armed for."""
    w = _WATCH
    if w is not None:
        w.finish()


def _stop_for_test() -> None:
    """Tests swap _WATCH with a fake; close the real one between runs."""
    global _WATCH
    with _LOCK:
        w, _WATCH = _WATCH, None
    if w is not None:
        w.close()
