"""Silence endpointing for an open-ended capture.

A toggle capture ends on the next press, but a lost key release or a
forgotten second press leaves the mic open until the hard cap. This tracks
the mic level (0..1, the same 10 Hz stream the overlay shows) and reports
when the speaker has finished: speech was heard, then `silence_s` of quiet.
A capture where nothing was ever said never fires; the hard cap
([audio] seconds) and the toggle press still end that one. Pure: `now` is
passed in.
"""

DEFAULT_SILENCE_S = 2.5
SPEECH_LEVEL = 0.12      # level at or above this counts as speech
MIN_SPEECH_S = 0.3       # total voiced time before silence can end a take
_MAX_DT = 0.5            # a stalled sampler does not count as voiced time


def silence_seconds(cfg) -> float:
    """[audio] silence_s; 0 (or junk) turns silence auto-stop off."""
    raw = ((cfg or {}).get("audio") or {}).get("silence_s",
                                                str(DEFAULT_SILENCE_S))
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_SILENCE_S


class SilenceEndpoint:
    def __init__(self, silence_s: float = DEFAULT_SILENCE_S,
                 speech_level: float = SPEECH_LEVEL,
                 min_speech_s: float = MIN_SPEECH_S):
        self.silence_s = silence_s
        self.speech_level = speech_level
        self.min_speech_s = min_speech_s
        self.speech_s = 0.0
        self.heard = False
        self.fired = False
        self._last = None
        self._quiet_since = None

    def feed(self, level: float, now: float) -> bool:
        """True once, when speech was heard and silence has lasted long
        enough. Disabled (silence_s <= 0) never fires."""
        dt = 0.0 if self._last is None else min(now - self._last, _MAX_DT)
        self._last = now
        if self.fired or self.silence_s <= 0:
            return False
        if level >= self.speech_level:
            self._quiet_since = None
            self.speech_s += dt
            if self.speech_s >= self.min_speech_s:
                self.heard = True
            return False
        if not self.heard:
            return False
        if self._quiet_since is None:
            self._quiet_since = now
        if now - self._quiet_since >= self.silence_s:
            self.fired = True
            return True
        return False
