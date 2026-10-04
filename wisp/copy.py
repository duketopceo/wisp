"""Shared UI copy (DESIGN-v2 5.9): one source for every surface.

Status words and tones, result-prefix translations and choice labels live
here. scripts/assets/gen_copy.py writes the same tables into
shell-plugin/lib/copy.js for the QML surfaces; tests/test_copy.py fails if
that file is stale. Rules are data (regex + template) so the JS side only
interprets them and cannot drift.

Copy rules: lowercase status words, human verbs, no protocol strings, no
em-dashes. Raw result text is kept as `detail` for a details disclosure.
"""
import re

# Tone names are Wisp token names (wisp/theme.py TOKENS) except "muted",
# which maps to inkMuted. `fail` is error only; `needsYou` is waiting on
# the user only.
TONES = ("ember", "needsYou", "fail", "ok", "muted")

# status -> (word, tone)
STATUS = {
    "idle": ("ready", "muted"),
    "listening": ("listening", "ember"),
    "transcribing": ("hearing you", "ember"),
    "deciding": ("thinking", "ember"),
    "acting": ("working", "ember"),
    "speaking": ("speaking", "ember"),
    "awaiting_choice": ("your call", "needsYou"),
    "suggestion": ("idea", "ember"),
    "done": ("done", "ok"),
    "error": ("that failed", "fail"),
    "offline": ("offline", "muted"),
}
UNKNOWN_STATUS = "offline"

# (pattern, text, state). Pattern is matched at the start of the result;
# "{1}" in text is the first group, cleaned of dashes. state is a creature
# state name or None. First match wins; no match passes the text through.
RESULT_RULES = (
    (r"^ASK_USER:?\s+(.*)$", "{1}", None),
    (r"^BLOCKED \(tool .* needs confirmation\)", "blocked: needs your ok",
     None),
    (r"^BLOCKED \(risk=", "blocked: too risky to do on my own", None),
    (r"^BLOCKED \(shell tool", "blocked: shell commands are off", None),
    (r"^BLOCKED \((.*)\)$", "blocked: {1}", None),
    (r"^BLOCKED", "blocked", None),
    (r"^SKIP(PED)? \(launch( route)? but no app identified\)",
     "didn't catch which app", "didnt_understand"),
    (r"^SKIP(PED)? \(unknown app", "didn't recognize that app",
     "didnt_understand"),
    (r"^SKIP(PED)? \((nothing to type|empty command|empty agent task"
     r"|empty pattern)\)", "didn't catch what to do", "didnt_understand"),
    (r"^SKIP(PED)? \(.* declined by user\)", "skipped, you said no", None),
    (r"^SKIP(PED)? \(.* needs user confirmation\)", "needs your ok", None),
    (r"^SKIP(PED)? \(shell disabled", "shell commands are off", None),
    (r"^SKIP(PED)?\b", "couldn't do that", None),
    (r"^(ERROR|FAIL|FAILED|REFUSED)\b", "that failed", None),
    (r"^(ABORTED|CANCELLED)\b", "stopped", None),
)

# choice pick "action:<verb>" -> label
ACTION_VERBS = {
    "launch": "open it", "run_shell": "run a command",
    "answer": "just answer", "act": "do it for me",
    "agent": "send to agent", "dictation": "dictate it",
}

# error_code -> (message, hint). Codes are the closed set in
# wisp/errors_codes.py (docs/IPC_CONTRACT.md "Error codes"); a code outside
# the set reads as `internal`. Message says what happened, hint says what
# to try. Shown by every surface; raw `error_detail` never is.
ERRORS = {
    "jev_down": ("can't reach the decision model",
                 "check the jev service, then try again"),
    "brain_down": ("can't reach the answering model",
                   "check your model endpoint, then try again"),
    "stt_down": ("can't hear you right now",
                 "check the speech service, then try again"),
    "ground_down": ("screen grounding is offline",
                    "check the grounding service, then try again"),
    "ground_failed": ("couldn't find that on screen",
                      "try again with the window in view"),
    "timeout": ("that took too long", "try again"),
    "cancelled": ("stopped", ""),
    "busy": ("still working on the last request",
             "wait for it to finish or say stop"),
    "stale_prompt": ("that question expired", "ask again"),
    "restarted": ("wisp restarted", "try again"),
    "tool_failed": ("a step failed", "open details to see which one"),
    "budget_exceeded": ("today's model budget is used up",
                        "raise the budget in settings or wait until tomorrow"),
    "internal": ("something went wrong", "open details, then try again"),
}
UNKNOWN_ERROR = "internal"

# Reader and surface strings keyed "area.name". Sentence case is not used
# for status-like words (lowercase), same as STATUS.
STRINGS = {
    "state.stale": "out of date",
    "state.reconnecting": "reconnecting",
    "state.offline": "wisp is not running",
    "state.degraded": "reading from file",
    "state.newer": "wisp is newer than this panel",
    "state.details": "details",
    "ui.more": "more",
    "ui.stop": "stop",
    "ui.talk": "talk",
    "ui.target.click": "click",
    "ui.target.unsure": "not sure",
    "ui.hide": "hide",
    "ui.esc": "esc",
    "ui.noted": "noted",
    "ui.undo": "undo",
    "ui.goal": "goal",
    "ui.pill.blocked": "blocked",
    "ui.label.good": "good",
    "ui.label.wrong": "wrong",
    "ui.steps.none": "no steps yet",
    "ui.step.confirm": "needs your ok",
    "ui.agent.queued": "queued",
    "ui.agent.running": "running",
    "ui.agent.done": "done",
    "ui.agent.failed": "failed",
    "ui.agent.cancelled": "cancelled",
    "ui.tab.now": "now",
    "ui.tab.agents": "agents",
    "ui.tab.memory": "memory",
    "ui.tab.settings": "settings",
    "ui.empty.now": "nothing happening right now",
    "ui.empty.now.hint": "hold the talk key and ask for something",
    "ui.empty.agents": "no agents running",
    "ui.empty.agents.hint": "say send it to an agent to start one",
    "ui.empty.memory": "nothing remembered yet",
    "ui.empty.memory.hint": "say remember that, then what to keep",
    "ui.empty.settings": "settings are not loaded",
    "ui.empty.settings.hint": "start wisp, then reopen this panel",
}

_DASH = re.compile(r"\s*[—–]\s*")


def _undash(s: str) -> str:
    return _DASH.sub(": ", s).strip()


def status_word(status: str) -> str:
    return STATUS.get(status, STATUS[UNKNOWN_STATUS])[0]


def status_tone(status: str) -> str:
    return STATUS.get(status, STATUS[UNKNOWN_STATUS])[1]


# result prefix that makes a finished turn read as blocked in the pill and
# the status chips: the daemon reports `done` with a BLOCKED result.
_BLOCKED = re.compile(r"^BLOCKED")


def pill_view(status: str, result: str = "") -> tuple:
    """(word, tone) for the pill: the status word, except a `done` turn
    whose result is BLOCKED reads `blocked` in the needs-you tone, never
    `done` (the action did not happen)."""
    if status == "done" and _BLOCKED.match(result or ""):
        return (STRINGS["ui.pill.blocked"], "needsYou")
    return (status_word(status), status_tone(status))


def translate_result(raw: str) -> dict:
    """Result text -> {text, state, detail}. detail is the raw string when
    it was translated (for a details disclosure), else ""."""
    raw = raw or ""
    for pattern, text, state in RESULT_RULES:
        m = re.match(pattern, raw)
        if m:
            if "{1}" in text:
                text = text.replace("{1}", _undash(m.group(1) or ""))
            return {"text": text, "state": state, "detail": raw}
    return {"text": raw, "state": None, "detail": ""}


def pick_label(pick: str) -> str:
    """Humanize a choice pick string for a chip label."""
    p = re.sub(r"^suggestion:", "", pick or "")
    kind, sep, val = p.partition(":")
    if not sep:
        return _undash(p)
    if kind == "app":
        return "none of these" if val == "none" else val
    if kind == "action":
        return ACTION_VERBS.get(val) or val.replace("_", " ")
    return _undash(val)


def error_message(code: str) -> str:
    return ERRORS.get(code, ERRORS[UNKNOWN_ERROR])[0]


def error_hint(code: str) -> str:
    return ERRORS.get(code, ERRORS[UNKNOWN_ERROR])[1]


def string(key: str) -> str:
    """UI string by key; unknown keys return the key so a typo is visible."""
    return STRINGS.get(key, key)
