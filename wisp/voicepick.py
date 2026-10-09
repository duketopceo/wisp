"""Spoken answers to pending prompts — map an utterance onto the offered
options so a card can be resolved by voice instead of a click.

map_pick(text, options) -> 0-based index or None:
- binary confirm cards ("... — yes" / "no") take affirm/negate words
- "the second one", "two", "2" take the ordinal
- otherwise word-overlap on option labels ('app:firefox' → 'firefox')

Pure: no I/O, no state. Callers decide what an unmapped utterance means.
"""
import re

_ORDINALS = {"first": 1, "one": 1, "second": 2, "two": 2, "third": 3,
             "three": 3, "fourth": 4, "four": 4, "fifth": 5, "five": 5,
             "sixth": 6, "six": 6}

_AFFIRM = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay",
           "do it", "go ahead", "go for it", "allow", "approve",
           "approved", "confirm", "proceed", "sounds good", "fine",
           "absolutely", "why not"}
_NEGATE = {"no", "nope", "nah", "cancel", "deny", "denied", "don't",
           "do not", "refuse", "negative", "stop", "never mind",
           "don't do it", "no thanks", "skip it"}

# interjection words while a turn runs (not a prompt answer)
_STOP = {"stop", "cancel", "never mind", "wait", "hold on", "halt",
         "don't", "do not", "not that", "nope", "no", "leave it",
         "forget it", "abort"}

_NUM = re.compile(r"^[0-9]+$")
_NONWORD = re.compile(r"[^a-z0-9' ]+")
_KIND = re.compile(r"^(app|action|tool|option|choice)\s*:")


def _norm(text: str) -> str:
    return " ".join(_NONWORD.sub(" ", (text or "").lower()).split())


def _said(t: str, vocab) -> bool:
    ws = set(t.split())
    for phrase in vocab:
        if " " in phrase:
            if phrase in t:
                return True
        elif phrase in ws:
            return True
    return False


def _label(option: str) -> str:
    """Speakable form of an option — 'app:firefox — yes' → 'firefox yes'."""
    return _norm(_KIND.sub("", option or ""))


def _is_confirm(options) -> bool:
    """The confirm card's shape: exactly two options, the last negative."""
    return (len(options) == 2
            and _label(options[-1]) in ("no", "deny", "cancel"))


def map_pick(text: str, options) -> int | None:
    """0-based index into options, or None when nothing maps."""
    if not options:
        return None
    t = _norm(text)
    if not t:
        return None
    if _is_confirm(options):
        if _said(t, _NEGATE):
            return len(options) - 1
        if _said(t, _AFFIRM):
            return 0
    # ordinals and digits bind before label overlap
    for w in t.split():
        if w in _ORDINALS:
            i = _ORDINALS[w]
            return i - 1 if i <= len(options) else None
        if _NUM.match(w):
            i = int(w)
            return i - 1 if 1 <= i <= len(options) else None
    # word overlap on labels — longest matched word wins; <3 chars never
    # bind ('it', 'go' would hit everything)
    best = None
    ws = set(t.split())
    for i, opt in enumerate(options):
        for w in _label(opt).split():
            if len(w) >= 3 and w in ws:
                if best is None or len(w) > best[0]:
                    best = (len(w), i)
    return best[1] if best else None


def is_stop(text: str) -> bool:
    """An interjection asking to halt the running turn."""
    return _said(_norm(text), _STOP)
