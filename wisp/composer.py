"""Double-Control typed composer (U1, KTD1). On by default.

Two non-consuming binds on a lone Control key (press and release) run the
light `fastkey.py tap down|up` client, which sends `tap` to the daemon.
Here a tap is a press held under TAP_S; two taps with at most DOUBLE_S
between the first release and the second press open the composer. Control
still reaches the app, so a chord such as Control+C cannot be observed
directly: the hold limit is the chord filter (a chord is held longer than
a tap). The timing mirrors `handsfree.Tracker` (press-to-release is a tap,
release-to-press is the double window) with KTD1's limits. Taps made while
the talk key is held are ignored.

If the binds cannot be installed, `[composer] fallback_chord` opens the
composer instead (`fastkey.py tap open`). `[composer] enabled = "false"`
turns the whole thing off.
"""
import time

TAP_S = 0.25      # press to release: shorter than this is a tap
DOUBLE_S = 0.35   # release of tap one to press of tap two
DEFAULT_FALLBACK = "SUPER + SHIFT + SPACE"


def _section(cfg) -> dict:
    return (cfg or {}).get("composer", {}) or {}


def enabled(cfg) -> bool:
    return str(_section(cfg).get("enabled", "true")).strip().lower() \
        != "false"


class TapDetector:
    """Pure: `feed(phase, now, talk_held)` -> True on the release that
    completes a double tap. `now` is passed in (an injected clock)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._down = None       # when the current press began
        self._tap_end = None    # release time of an unpaired first tap

    def feed(self, phase: str, now: float, talk_held: bool = False) -> bool:
        if talk_held:
            self.reset()
            return False
        if phase == "down":
            if self._down is None:   # key repeat sends no second down
                self._down = now
            return False
        if phase != "up" or self._down is None:
            return False
        held = now - self._down
        started = self._down
        self._down = None
        if held >= TAP_S:            # held: a chord or a hold, not a tap
            self._tap_end = None
            return False
        if self._tap_end is not None and started - self._tap_end <= DOUBLE_S:
            self._tap_end = None
            return True
        self._tap_end = now
        return False


_DETECTOR = TapDetector()


def reset():
    _DETECTOR.reset()


def handle_tap(cfg, phase: str, now: float | None = None,
               talk_held: bool = False) -> bool:
    """The daemon's `tap` handler. True when the composer should open.
    Phase `open` (the fallback chord) opens at once."""
    if not enabled(cfg):
        return False
    if phase == "open":
        return True
    return _DETECTOR.feed(phase, time.monotonic() if now is None else now,
                          talk_held)


def install(cfg, runner: list, hypr_mod) -> dict:
    """Bind the double-Control pair; on failure, the fallback chord.
    `runner` is the argv prefix of the fastkey client, `hypr_mod` the
    bind registry (wisp.hypr). Never raises. -> {"mode": "double-ctrl" |
    "chord" | "none", "chord": str, "error": str}"""
    if not enabled(cfg):
        return {"mode": "none", "chord": "", "error": "disabled"}
    err = ""
    made = []
    try:
        for phase in ("down", "up"):
            made.append(hypr_mod.bind(
                "CONTROL", list(runner) + ["tap", phase], lone=True,
                non_consuming=True, release=(phase == "up")))
        return {"mode": "double-ctrl", "chord": "CONTROL", "error": ""}
    except Exception as e:
        err = str(e)
        for h in made:           # never leave a press without its release
            try:
                hypr_mod.unbind(h)
            except Exception:
                pass
    chord = str(_section(cfg).get("fallback_chord", DEFAULT_FALLBACK)).strip()
    if chord:
        try:
            hypr_mod.bind(chord, list(runner) + ["tap", "open"])
            return {"mode": "chord", "chord": chord, "error": err}
        except Exception as e:
            err = f"{err}; {e}"
    return {"mode": "none", "chord": "", "error": err}
