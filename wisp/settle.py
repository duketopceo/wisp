"""Settle: has the screen reacted to what the user just did, and stopped?

Frames are downsampled grayscale bytes (one byte per pixel, equal length).
Two frames differ by the mean absolute luma difference over 255. A screen
is *settled* once it has changed after the watch started and then held
steady for `SETTLE_WINDOW_S`. A screen that never changes is not settled
(the user has not done anything yet) and one that keeps changing is not
settled either (a page still loading, a video playing).

The frame source is an injected callable `() -> bytes | None`, so tests
feed synthetic sequences. Production uses `grim_frame`, which polls the
active window with grim and shells out to nothing else.
"""
from __future__ import annotations

import re
import subprocess
import time

# grim at 5% scale of the whole layout took 299 ms p50 and 454 ms max over
# 8 runs on the dev machine (spike, docs/research/2026-11-05-click-
# observation-spike.md), so polling any faster only queues captures.
SETTLE_POLL_S = 0.3
GRIM_SCALE = 0.05

# Mean absolute luma difference, 0..1, between two consecutive frames at
# about 96x60 px (a 1920x1200 window at GRIM_SCALE). The synthetic frames
# in tests/test_settle.py give a blinking text cursor (2x2 px) 0.0007 and
# an opening dropdown (20x30 px) 0.08, so 0.005 sits about 7x above the
# blink and 16x below the dropdown. tests/test_settle.py asserts both.
SETTLE_DIFF = 0.005

# Three consecutive quiet polls at SETTLE_POLL_S: a single quiet poll is
# the pause between a click and the app starting to react.
SETTLE_WINDOW_S = 0.9


def frame_diff(a: bytes, b: bytes) -> float:
    """Mean absolute luma difference of two equal-size frames, 0..1.
    Frames of different size (a window resized) count as fully changed."""
    if not a or not b or len(a) != len(b):
        return 1.0
    return sum(abs(x - y) for x, y in zip(a, b)) / (255.0 * len(a))


class SettleWatch:
    """Poll-driven: `poll(now)` is True once the screen changed and then
    held steady for the window. Never advances on a frozen or failed
    source."""

    poll_s = SETTLE_POLL_S

    def __init__(self, frame, *, window_s: float = SETTLE_WINDOW_S,
                 threshold: float = SETTLE_DIFF):
        self.frame = frame
        self.window_s, self.threshold = window_s, threshold
        self.prev = None
        self.changed = False
        self.quiet_since = None

    def poll(self, now: float) -> bool:
        cur = self.frame()
        if cur is None:
            return False
        prev, self.prev = self.prev, cur
        if prev is None:
            return False
        if frame_diff(prev, cur) >= self.threshold:
            self.changed = True
            self.quiet_since = None
            return False
        if not self.changed:
            return False
        if self.quiet_since is None:
            self.quiet_since = now
        return now - self.quiet_since >= self.window_s


def wait_settled(frame, timeout: float, *, sleep=time.sleep,
                 clock=time.monotonic, check=None,
                 window_s: float = SETTLE_WINDOW_S,
                 threshold: float = SETTLE_DIFF) -> bool:
    """True when the screen changed and settled within `timeout`; False
    when it never changed or never stopped changing."""
    watch = SettleWatch(frame, window_s=window_s, threshold=threshold)
    end = clock() + timeout
    while True:
        if watch.poll(clock()):
            return True
        if clock() >= end:
            return False
        if check is not None:
            check()
        sleep(watch.poll_s)


_PPM = re.compile(rb"P6\s+(\d+)\s+(\d+)\s+255\s")


def _gray(ppm: bytes) -> bytes | None:
    """Luma bytes from a binary PPM (P6, maxval 255), else None."""
    m = _PPM.match(ppm)
    if not m:
        return None
    n = int(m.group(1)) * int(m.group(2)) * 3
    px = ppm[m.end():m.end() + n]
    if not n or len(px) < n:
        return None
    return bytes((px[i] + px[i + 1] + px[i + 2]) // 3
                 for i in range(0, n, 3))


def grim_frame(window: dict | None = None) -> bytes | None:
    """One downsampled grayscale frame of `window` (the active window's
    `at`/`size`, logical px) or of the whole layout, or None when grim
    is missing or fails. The pixels stay in memory and are never saved."""
    cmd = ["grim", "-s", str(GRIM_SCALE), "-t", "ppm"]
    try:
        at, size = window["at"], window["size"]
        cmd += ["-g", f"{int(at[0])},{int(at[1])} {int(size[0])}x{int(size[1])}"]
    except (TypeError, KeyError, IndexError, ValueError):
        pass
    cmd.append("-")
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return _gray(r.stdout) if r.returncode == 0 else None
