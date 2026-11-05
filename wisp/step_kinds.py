"""Step kinds: how a walkthrough step is drawn and how it is completed.

Every step declares one kind from Wisp's own small vocabulary. The kind
fixes the overlay primitive and the evidence that advances the step:

| kind          | meaning                                  | advances on      |
|---------------|------------------------------------------|------------------|
| click         | one atomic click the app will show       | click in radius  |
| hover         | reveal something by hovering             | pointer rest     |
| area          | a region matters, no single control      | settle or voice  |
| handle        | a thing to grab or drag from             | settle or voice  |
| motion        | direction of a drag or swipe             | settle or voice  |
| voice-confirm | not detectable (type text, set a value)  | "continue"       |

`voice-confirm` is the only kind that never claims Wisp can see the user
act, so it is the fallback for anything unknown or malformed. The parser
never raises.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

CLICK = "click"
HOVER = "hover"
AREA = "area"
HANDLE = "handle"
MOTION = "motion"
VOICE_CONFIRM = "voice-confirm"

KINDS = (CLICK, HOVER, AREA, HANDLE, MOTION, VOICE_CONFIRM)

# Kind -> (drawn as, advances on). Pinned by tests; drawn by the overlay.
TABLE = {
    CLICK: ("ring with radius", "click in radius"),
    HOVER: ("dashed ring", "pointer rest"),
    AREA: ("soft highlight region", "settle or voice"),
    HANDLE: ("small marker", "settle or voice"),
    MOTION: ("arrow or curve", "settle or voice"),
    VOICE_CONFIRM: ("none, caption chip", "continue"),
}

# Logical px. The ring Wisp draws around a target in the recorded turn
# fixture tests/fixtures/turns/answer_draw_timed.json is [RING:100,200,30],
# so a click within the same 30 px of the target counts as on it.
DEFAULT_CLICK_RADIUS = 30

_RADIUS_MIN, _RADIUS_MAX = 4, 400

_warned: set = set()

# A step that asks the user to type or choose a value cannot be seen as a
# click, whatever the model called it.
_FIELD_LABEL = re.compile(
    r"\b(search|text|input|address|url|password|name|email|filename|file name)"
    r"\s*(box|field|bar|entry|input)\b|\btextbox\b|\btext area\b",
    re.IGNORECASE)
_ENTRY_VERB = re.compile(r"^\s*(type|paste|write)\b", re.IGNORECASE)


def parse_kind(raw) -> str:
    """The kind named by `raw`; unknown or missing falls back to
    voice-confirm. An unknown name is logged once."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return CLICK
    name = str(raw).strip().lower().replace("_", "-").replace(" ", "-")
    if name == "voice":
        name = VOICE_CONFIRM
    if name in KINDS:
        return name
    if name not in _warned:
        _warned.add(name)
        log.warning("unknown step kind %r, using voice-confirm", str(raw)[:40])
    return VOICE_CONFIRM


def parse_radius(raw) -> int | None:
    """A usable radius in logical px, or None."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    r = int(raw)
    return r if _RADIUS_MIN <= r <= _RADIUS_MAX else None


def is_text_entry(text: str, label: str) -> bool:
    return bool(_FIELD_LABEL.search(label or "")
                or _ENTRY_VERB.match(text or ""))


def settle_kind(kind: str, text: str = "", label: str = "") -> str:
    """The kind a step is delivered as: a text-entry step planned as a
    click becomes voice-confirm."""
    if kind == CLICK and is_text_entry(text, label):
        return VOICE_CONFIRM
    return kind


def effective_radius(kind: str, radius: int | None) -> int | None:
    """The radius to test a click against: the planned one, else the
    default for click steps, else None."""
    if radius is not None:
        return radius
    return DEFAULT_CLICK_RADIUS if kind == CLICK else None


def _reset_warned() -> None:
    _warned.clear()
