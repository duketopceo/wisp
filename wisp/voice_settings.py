"""Spoken voice settings (B8): "talk slower", "talk faster", "normal speed".

A spoken setting goes through the same `config.set_config` the `config`
IPC verb uses (so the same validation and the same file), and leaves a
`config` entry in the audit log next to the guarded calls.
"""
import re

from . import config, cua_safety, speech

_PRE = r"^\s*(?:(?:hey\s+)?wisp[,\s]+)?(?:please\s+)?"
_SLOWER = re.compile(
    _PRE + r"(?:(?:talk|speak)\s+(?:a\s+(?:bit|little)\s+)?"
    r"(?:slower|more\s+slowly)|slow\s+(?:down|it\s+down)|slower)"
    r"(?:\s+please)?[\s.!?]*$", re.IGNORECASE)
_FASTER = re.compile(
    _PRE + r"(?:(?:talk|speak)\s+(?:a\s+(?:bit|little)\s+)?"
    r"(?:faster|more\s+quickly)|speed\s+(?:up|it\s+up)|faster)"
    r"(?:\s+please)?[\s.!?]*$", re.IGNORECASE)
_NORMAL = re.compile(
    _PRE + r"(?:(?:talk|speak)\s+(?:at\s+)?(?:a\s+)?normal(?:ly)?"
    r"(?:\s+(?:speed|pace|rate))?|normal\s+(?:speed|pace|rate))"
    r"(?:\s+please)?[\s.!?]*$", re.IGNORECASE)

PREFIX = "voice-speed:"


def intent(text: str):
    """"slower" | "faster" | "normal" for a spoken speed request, else
    None."""
    t = text or ""
    if _SLOWER.match(t):
        return "slower"
    if _FASTER.match(t):
        return "faster"
    if _NORMAL.match(t):
        return "normal"
    return None


def _nearest(v: float) -> int:
    steps = speech.SPEED_STEPS
    return min(range(len(steps)), key=lambda i: abs(steps[i] - v))


def apply(kind: str, cfg: dict, turn: str = "") -> str:
    """Change [voice] speed one step (or back to 1.0) and return the line
    to speak. The live `cfg` is updated so the reply is spoken at the new
    speed."""
    steps = speech.SPEED_STEPS
    i = _nearest(speech.speed(cfg))
    if kind == "normal":
        j = steps.index(1.0)
    elif kind == "slower":
        j = max(0, i - 1)
    else:
        j = min(len(steps) - 1, i + 1)
    if j == i and kind != "normal":
        edge = "slow" if kind == "slower" else "fast"
        return f"ACTED (0 steps): I'm already as {edge} as I go."
    value = f"{steps[j]:g}"
    try:
        config.set_config("voice", "speed", value)
    except ValueError as e:
        return f"SKIP (couldn't change the speed: {e})"
    cfg.setdefault("voice", {})["speed"] = value
    cua_safety.audit_event("config", "voice", cfg, turn=turn,
                           setting="voice.speed", value=value)
    word = {"slower": "slower", "faster": "faster",
            "normal": "at normal speed"}[kind]
    return f"ACTED (0 steps): okay, talking {word}."
