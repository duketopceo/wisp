"""Reject transcripts that are speech-model junk before a turn runs.

A model primed with a word list can echo the list back, loop one token, or
invent a long sentence from a clip with almost no speech. Routing such text
runs a real turn on nothing. `looks_like_garbage` is deterministic and
conservative: ordinary short commands and questions never trip it.
"""
import re
import wave

REPLY = "I didn't catch that"

REPEAT_RUN = 3            # the same token this many times in a row
ECHO_MIN_WORDS = 5        # echo needs a sentence long enough to judge
ECHO_SHARE = 0.6          # share of words found in the priming prompt
LONG_CLIP_S = 8.0         # a "long" clip for the words-per-second check
MIN_WPS = 0.3

_TOKEN = re.compile(r"[a-z0-9][a-z0-9'.+-]*")


def _tokens(text: str) -> list:
    return [t.strip(".'-+") for t in _TOKEN.findall((text or "").lower())
            if t.strip(".'-+")]


def wav_seconds(path) -> float:
    """Clip length in seconds, 0.0 when it cannot be read."""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (OSError, EOFError, wave.Error):
        return 0.0


def looks_like_garbage(text: str, prompt: str = "",
                       duration_s: float = 0.0) -> str:
    """"" when the transcript is fine, else a short reason code:
    `repeat`, `prompt_echo` or `sparse`."""
    words = _tokens(text)
    if not words:
        return ""
    run = 1
    for a, b in zip(words, words[1:]):
        run = run + 1 if a == b else 1
        if run >= REPEAT_RUN:
            return "repeat"
    known = set(_tokens(prompt))
    if known and len(words) >= ECHO_MIN_WORDS:
        hits = sum(1 for w in words if w in known)
        if hits / len(words) >= ECHO_SHARE:
            return "prompt_echo"
    if duration_s >= LONG_CLIP_S and len(words) / duration_s < MIN_WPS:
        return "sparse"
    return ""
