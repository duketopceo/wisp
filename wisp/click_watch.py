"""Did the user click the thing Wisp pointed at?

Hyprland gives an unprivileged process no button-press event (its event
socket carries focus, layout and workspace events, not pointer buttons;
docs/research/2026-11-05-click-observation-spike.md), and reading
/dev/input needs the input group. What it does give, at 0.03 ms a query,
is the pointer position. A click is therefore inferred: the pointer is at
rest and the screen reacted (see settle.py `frame_diff`). Inside the
step's radius that is "clicked-in"; somewhere else after the pointer
travelled there it is "clicked-out". A click the app shows no reaction to
is not seen; the walkthrough's own stuck prompt and the user's "continue"
cover it.

Sources are injected callables so tests need no desktop:
`cursor() -> (x, y) | None` and `frame() -> bytes | None`.
"""
from __future__ import annotations

import math
import time

from . import settle

CLICKED_IN = "clicked-in"
CLICKED_OUT = "clicked-out"
NONE = "none"
RESTED = "rested"

# The cursor query answers in 0.03 ms p50 / 0.09 ms max over 50 calls
# (spike), so polling is bounded by the frame grab that follows a rest,
# not by this. 0.1 s keeps a click's reaction within one or two polls
# without running grim while the pointer is still travelling.
CLICK_POLL_S = 0.1

# The pointer must sit still this long before a screen change counts as a
# reaction to a click rather than to the pointer sweeping across hover
# effects. Two polls at CLICK_POLL_S.
CLICK_REST_S = 0.2

# Hover steps advance after the pointer rests inside the radius this long.
# GTK shows a tooltip after 500 ms (gtk-tooltip-timeout default) and web
# hover menus use similar delays, so 0.8 s lets the reveal appear before
# Wisp moves on. Not measured on a live session: on the owner's checklist.
HOVER_REST_S = 0.8


def hypr_cursor():
    """The pointer in logical layout px from the Hyprland socket, or
    None when Hyprland is not reachable."""
    try:
        from . import hypr
        p = hypr.query("cursorpos")
        return int(p["x"]), int(p["y"])
    except (ImportError, RuntimeError, KeyError, TypeError, ValueError):
        return None


def _inside(pos, target, radius) -> bool:
    return math.hypot(pos[0] - target[0], pos[1] - target[1]) <= radius


class ClickWatch:
    """`poll(now)` returns CLICKED_IN, CLICKED_OUT or None."""

    poll_s = CLICK_POLL_S

    def __init__(self, target, radius, cursor, frame,
                 rest_s: float = CLICK_REST_S):
        self.target, self.radius = target, radius
        self.cursor, self.frame, self.rest_s = cursor, frame, rest_s
        self.pos = None
        self.moved_at = None
        self.travelled = False
        self.baseline = None
        self.rebase = True

    def poll(self, now: float):
        pos = self.cursor()
        if pos is None:
            return None
        if pos != self.pos:
            if self.pos is not None:
                self.travelled = True
            self.pos, self.moved_at, self.rebase = pos, now, True
            return None
        if self.moved_at is not None and now - self.moved_at < self.rest_s:
            return None
        cur = self.frame()
        if cur is None:
            return None
        if self.baseline is None or self.rebase:
            self.baseline, self.rebase = cur, False
            return None
        if settle.frame_diff(self.baseline, cur) < settle.SETTLE_DIFF:
            return None
        if _inside(pos, self.target, self.radius):
            return CLICKED_IN
        # A reaction with the pointer elsewhere is only a stray click when
        # the pointer went there: a page animating under a parked pointer
        # is not.
        return CLICKED_OUT if self.travelled else None


class HoverWatch:
    """`poll(now)` returns RESTED once the pointer has stayed put inside
    the radius for HOVER_REST_S."""

    poll_s = CLICK_POLL_S

    def __init__(self, target, radius, cursor, rest_s: float = HOVER_REST_S):
        self.target, self.radius = target, radius
        self.cursor, self.rest_s = cursor, rest_s
        self.pos = None
        self.since = None

    def poll(self, now: float):
        pos = self.cursor()
        if pos is None or not _inside(pos, self.target, self.radius):
            self.pos = self.since = None
            return None
        if pos != self.pos:
            self.pos, self.since = pos, now
            return None
        return RESTED if now - self.since >= self.rest_s else None


def wait_click(target, radius, timeout: float, *, cursor=hypr_cursor,
               frame=None, sleep=time.sleep, clock=time.monotonic,
               check=None) -> str:
    """Block up to `timeout` s for a click: "clicked-in" (inside `radius`
    px of `target`), "clicked-out", or "none"."""
    if frame is None:
        frame = settle.grim_frame
    watch = ClickWatch(target, radius, cursor, frame)
    end = clock() + timeout
    while True:
        got = watch.poll(clock())
        if got:
            return got
        if clock() >= end:
            return NONE
        if check is not None:
            check()
        sleep(watch.poll_s)
