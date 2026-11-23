"""The one status table (wisp-one-surface plan KTD1).

Every daemon status, plus the states the surfaces derive from it (a
pending confirmation, a blocked turn, a stale turn), has one row here:
the main word, the short word the narrow bar pill may use, the tone, the
mark glyph, the bar pill treatment, the creature state and the buddy mode.

Words are copy keys. The text lives in wisp/copy.py STRINGS, so this file
holds no user-visible text. A short word must equal the main word or be a
prefix of it, so the bar can never name a status differently from the
Panel. scripts/assets/gen_status.py writes the same table into
shell-plugin/lib/status.js; wisp/copy.py derives STATUS and word_view
from it, so the CLI reads the same rows.

Tones are Wisp token names (wisp/theme.py TOKENS) except "muted", which
maps to inkMuted. mark_token and creature_token are token names. A pill
of None means the bar shows the mark alone.
"""

# Daemon statuses (the keys of wisp/copy.py STATUS), in display order.
STATUSES = ("idle", "listening", "transcribing", "deciding", "acting",
            "speaking", "awaiting_choice", "suggestion", "done", "error",
            "offline")

# States the surfaces compute from a status plus context.
DERIVED = ("confirm", "blocked", "stale")

UNKNOWN_STATUS = "offline"

# statuses in which the daemon must keep publishing (the reader's BUSY set,
# shell-plugin/lib/state.js); a stale flag only means something here
BUSY = ("transcribing", "deciding", "acting")


def _pill(kind, glyph, token, border="keyline", word_token="ink",
          when="always"):
    return {"kind": kind, "glyph": glyph, "token": token, "border": border,
            "word_token": word_token, "when": when}


_NEEDS = _pill("needsYou", "warning", "needsYou", "needsYou", "needsYou")

# Error cause word per error code: one muted word on the bar pill.
CAUSES = {
    "jev_down": "status.cause.model", "brain_down": "status.cause.model",
    "stt_down": "status.cause.speech", "ground_down": "status.cause.screen",
    "ground_failed": "status.cause.screen", "timeout": "status.cause.timeout",
    "busy": "status.cause.busy", "tool_failed": "status.cause.tool",
    "budget_exceeded": "status.cause.budget",
    "key_missing": "status.cause.key", "region_denied": "status.cause.region",
    "restarted": "status.cause.restart", "stale_prompt": "status.cause.stale",
}


def _row(word, tone, glyph, mark_token, creature, creature_token="ember",
         buddy="hidden", pill=None, short=None, causes=None):
    return {"word": word, "short": short or word, "tone": tone,
            "glyph": glyph, "mark_token": mark_token, "creature": creature,
            "creature_token": creature_token, "buddy": buddy, "pill": pill,
            "causes": causes or {}}


ROWS = {
    "idle": _row("status.idle", "muted", "bar-idle", "ink", "idle"),
    "listening": _row("status.listening", "ember", "bar-listening", "ember",
                      "listening", buddy="waveform",
                      pill=_pill("listening", "waveform", "ember")),
    "transcribing": _row("status.transcribing", "ember", "bar-thinking",
                         "ember", "transcribing", buddy="spinner",
                         short="status.transcribing.short",
                         pill=_pill("thinking", "arc", "ember")),
    "deciding": _row("status.deciding", "ember", "bar-thinking", "ember",
                     "thinking", buddy="spinner",
                     pill=_pill("thinking", "arc", "ember")),
    "acting": _row("status.acting", "ember", "bar-acting", "ember", "acting",
                   buddy="spinner", pill=_pill("acting", "act", "ember")),
    "speaking": _row("status.speaking", "ember", "bar-thinking", "ember",
                     "speaking", buddy="triangle",
                     pill=_pill("speaking", "triangle", "ember")),
    "awaiting_choice": _row("status.awaiting_choice", "needsYou",
                            "bar-needs-you", "needsYou", "awaiting_choice",
                            creature_token="needsYou",
                            buddy="triangleNeedsYou", pill=_NEEDS),
    "suggestion": _row("status.suggestion", "ember", "bar-idle", "accent",
                       "suggestion"),
    "done": _row("status.done", "ok", "bar-idle", "ink", "done",
                 pill=_pill("done", "check", "ok", when="rated")),
    "error": _row("status.error", "fail", "bar-error", "fail", "error",
                  creature_token="fail", causes=CAUSES,
                  pill=_pill("error", "cross", "fail", "fail", "fail")),
    "offline": _row("status.offline", "muted", "bar-offline", "inkMuted",
                    "offline", creature_token="inkMuted"),
    # derived: a pending confirmation reads as the user's call
    "confirm": _row("status.awaiting_choice", "needsYou", "bar-needs-you",
                    "needsYou", "awaiting_choice",
                    creature_token="needsYou", pill=_NEEDS),
    # derived: a done turn whose result is BLOCKED
    "blocked": _row("ui.pill.blocked", "needsYou", "bar-needs-you",
                    "needsYou", "done", pill=_NEEDS),
    # derived: a busy turn whose state stopped updating
    "stale": _row("state.reconnecting", "muted", "bar-offline", "inkMuted",
                  "offline", creature_token="inkMuted"),
}


def row(status: str) -> dict:
    """The row for a daemon status; an unknown one reads as offline."""
    return ROWS[status if status in STATUSES else UNKNOWN_STATUS]
