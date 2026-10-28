"""Hands-free by double-tap (B33). Off by default.

`[handsfree] enabled = "true"` turns it on. The key binds still send
`wispd trigger start` on press and `stop` on release; this sits in front of
them and reads the pattern:

    tap, tap-and-hold-release   ->  start listening, keep listening
    next tap                    ->  stop and send

A tap is a press and release inside TAP_S. Holding the key behaves exactly
as before (hold to talk, release to send). With the setting off, `intercept`
returns None before touching anything, so hold-to-talk is the same code
path as before this module existed.
"""
import time

TAP_S = 0.4        # press to release: shorter than this is a tap
DOUBLE_S = 0.45    # release of tap one to press of tap two
MAX_LATCH_S = 120.0  # a latched mic never stays open longer than this


def enabled(cfg) -> bool:
    v = ((cfg or {}).get("handsfree", {}) or {}).get("enabled", "false")
    return str(v).strip().lower() == "true"


class Tracker:
    """Decides, per press/release, whether the daemon should see it.

    `decide(phase, now)` returns the phase to hand the daemon ("start",
    "stop") or None to swallow the event. Pure: `now` is passed in."""

    def __init__(self):
        self.latched = False
        self._pending = False       # second press seen, waiting for release
        self._down = None           # when the current press began
        self._tap_end = None        # when the last tap was released
        self._latched_at = 0.0
        self._swallow = False       # the release that ends a latched session

    def reset(self):
        self.__init__()

    def decide(self, phase: str, now: float):
        if self.latched and now - self._latched_at > MAX_LATCH_S:
            self.reset()
        if phase == "start":
            self._down = now
            if self.latched:
                self.latched = False
                self._swallow = True
                self._tap_end = None
                return "stop"       # the next tap ends hands-free
            if self._tap_end is not None and now - self._tap_end <= DOUBLE_S:
                self._pending = True
            return "start"
        if phase == "stop":
            held = now - self._down if self._down is not None else TAP_S
            self._down = None
            if self._swallow:
                self._swallow = False
                return None
            if self._pending:
                self._pending = False
                self._tap_end = None
                self.latched = True
                self._latched_at = now
                return None         # keep the recorder running
            if held < TAP_S:
                self._tap_end = now
            else:
                self._tap_end = None
            return "stop"
        return phase


_TRACKER = Tracker()


def intercept(cfg, phase: str, now: float | None = None):
    """The daemon's listen handler calls this first. Returns None when
    hands-free is off (nothing changes), else (phase_to_use) where
    phase_to_use is "start", "stop", or "" meaning swallow the event."""
    if phase not in ("start", "stop") or not enabled(cfg):
        return None
    out = _TRACKER.decide(phase, time.monotonic() if now is None else now)
    return out or ""


def interrupted():
    """Esc or an interrupt ends a latched session."""
    _TRACKER.reset()


def latched() -> bool:
    return _TRACKER.latched
