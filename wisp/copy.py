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
    (r"^SWITCHED tab\s+'([^']+)'\s*->\s*(\S+)$", "switched to {1}", None),
    (r"^OPENED\s+(\S+)\s*->\s*(.+)$", "opened {1}", None),
    (r"^LAUNCHED\s+([^\s-]+?)\s*->\s*(.+)$", "opened {1}", None),
    (r"^FOCUSED\s+([^\s-]+?)(?:\s*->.*)?$", "focused {1}", None),
    (r"^WORKSPACE\s+(\d+)\b", "workspace {1}", None),
    (r"^MEDIA\s+([a-z_]+)\b", "media {1}", None),
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
    (r"^SKIP(PED)? \(.* (handoff|confirmation) timed out\)",
     "skipped, no answer", None),
    (r"^SKIP(PED)? \(.* needs a human",
     "skipped, needed you to do it", None),
    (r"^HANDED_OFF ", "you handled it", None),
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
    "key_missing": ("an api key is missing",
                    "run wispd onboard to add it"),
    "internal": ("something went wrong", "open details, then try again"),
}
UNKNOWN_ERROR = "internal"

# Reader and surface strings keyed "area.name". Sentence case is not used
# for status-like words (lowercase), same as STATUS.
STRINGS = {
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
    "ui.rate.good": "rated good",
    "ui.rate.wrong": "rated wrong",
    "ui.rate.not_found": "nothing to rate",
    "ui.rate.not_ratable": "that turn did not finish",
    "ui.rate.note": "what went wrong? (optional)",
    "ui.steps.none": "no steps yet",
    "ui.step.confirm": "needs your ok",
    "ui.agent.queued": "queued",
    "ui.agent.running": "running",
    "ui.agent.done": "done",
    "ui.agent.failed": "failed",
    "ui.agent.cancelled": "cancelled",
    "ui.agent.interrupted": "interrupted",
    "ui.tab.now": "now",
    "ui.tab.agents": "agents",
    "ui.tab.memory": "memory",
    "ui.tab.settings": "settings",
    "ui.tab.devtab": "dev",
    "ui.bar.badge": "dev",
    "ui.dev.local": "local",
    "ui.dev.gate": "v1 gate",
    "ui.dev.of": "of",
    "ui.dev.labelled": "labelled",
    "ui.dev.rated": "rated",
    "ui.dev.of_turns": "of turns",
    "ui.dev.recent": "recent turns",
    "ui.dev.misses": "top misses",
    "ui.dev.step": "step",
    "ui.dev.steps": "steps",
    "ui.dev.refresh": "refresh",
    "ui.dev.empty": "no turns yet",
    "ui.dev.empty.hint": "ask wisp something, then refresh",
    "ui.dev.loading": "reading recent turns",
    "ui.dev.error": "could not read the turn log",
    "ui.dev.error.hint": "start wisp, then refresh",
    "ui.dev.badge.one": "run left",
    "ui.dev.badge.many": "runs left",
    "ui.dev.runs": "latest run",
    "ui.dev.runs.empty": "no runs yet",
    "ui.dev.runs.empty.hint": "turn dev mode on, then run a task list",
    "ui.dev.runs.error": "could not read the runs",
    "ui.dev.runs.tasks": "tasks",
    "ui.dev.runs.judged": "judged",
    "ui.dev.runs.confirmed": "confirmed",
    "ui.dev.runs.drift": "drift",
    "ui.dev.runs.cost": "cost",
    "ui.dev.runs.vs": "A/B",
    "ui.dev.out.success": "success",
    "ui.dev.out.stopped": "stopped",
    "ui.dev.out.incomplete": "incomplete",
    "ui.dev.out.wrong_tries": "wrong tries",
    "ui.dev.out.unjudged": "unjudged",
    "ui.dev.pair.a": "A better",
    "ui.dev.pair.b": "B better",
    "ui.dev.pair.tie": "tie",
    "ui.empty.now": "nothing happening right now",
    "ui.empty.now.hint": "hold the talk key and ask for something",
    "ui.empty.agents": "no agents running",
    "ui.empty.agents.hint": "say send it to an agent to start one",
    "ui.empty.memory": "nothing remembered yet",
    "ui.empty.memory.hint": "say remember that, then what to keep",
    "ui.empty.settings": "settings are not loaded",
    "ui.empty.settings.hint": "start wisp, then reopen this panel",
    "ui.now.asks": "wisp asks",
    "ui.run.step": "step",
    "ui.run.steps": "steps",
    "ui.run.change": "change",
    "ui.run.changes": "changes",
    "ui.question.hint": "say the answer, or type it in the panel",
    "ui.question.answer": "type the answer",
    "ui.question.send": "send",
    "ui.now.right": "was that right?",
    "ui.now.yes": "yes",
    "ui.now.no": "no",
    "ui.now.recent": "recent turns",
    "ui.memory.skills": "skills",
    "ui.memory.activity": "recent decisions",
    "ui.memory.more": "more in wispd skills",
    "ui.memory.failed": "needs attention",
    "ui.settings.health": "health",
    "ui.settings.budget": "budget",
    "ui.settings.pointer": "pointer",
    "ui.settings.cua": "cua safety",
    "ui.settings.connect": "connectors",
    "ui.settings.connect.none": "no connectors, run wispd inventory",
    "ui.settings.connect.go": "connect",
    "ui.set.daily": "daily cap in usd",
    "ui.set.monthly": "monthly cap in usd",
    "ui.set.pointer": "pointer mode",
    "ui.set.dry_run": "dry run",
    "ui.set.kill": "kill switch",
    "ui.set.confirm": "confirm",
    "ui.set.delivery": "delivery",
    "ui.set.clicks": "clicks per minute",
    "ui.set.per_turn": "actions per turn",
    "ui.settings.agent": "agent",
    "ui.settings.voice": "voice and talkback",
    "ui.settings.dictation": "dictation",
    "ui.set.autonomy": "autonomy",
    "ui.set.dictation": "dictation mode",
    "ui.set.voice": "spoken replies",
    "ui.set.tts_voice": "voice",
    "ui.set.captions": "live captions",
    "ui.set.on": "on",
    "ui.set.off": "off",
    "ui.set.advanced.show": "advanced safety & limits",
    "ui.set.advanced.hide": "hide advanced",
    "ui.set.save": "save",
    "ui.set.saved": "saved",
    "ui.set.blank": "blank means no cap",
    "ui.err.number": "enter a plain number",
    "ui.err.range": "that number is out of range",
    "ui.err.choice": "pick one of the options",
    "ui.err.chars": "no quotes, backslash or hash",
    "ui.err.unknown": "that setting can't be changed here",
    "ui.onboard.title": "set up wisp",
    "ui.onboard.progress": "steps done",
    "ui.onboard.step.mic": "microphone",
    "ui.onboard.step.models": "local models",
    "ui.onboard.step.cua": "cua pointer driver",
    "ui.onboard.step.notifications": "notifications",
    "ui.onboard.step.keybinding": "keybinding",
    "ui.onboard.state.done": "done",
    "ui.onboard.state.todo": "to do",
    "ui.onboard.state.skipped": "skipped",
    "ui.onboard.state.na": "not available",
    "ui.onboard.optional": "optional",
    "ui.onboard.run": "check",
    "ui.onboard.run.notifications": "send a test",
    "ui.onboard.again": "check again",
    "ui.onboard.skip": "skip",
    "ui.onboard.undo": "undo",
    "ui.onboard.finish": "finish setup",
    "ui.whatsnew.title": "what's new in",
    "ui.whatsnew.more": "more in the changelog",
    "ui.whatsnew.link": "changelog",
    "ui.whatsnew.dismiss": "got it",
    "ui.health.endpoints": "endpoints",
    "ui.health.none": "none configured",
    "ui.health.stt": "speech",
    "ui.health.cua": "cua",
    "ui.health.spend": "spend",
    "ui.health.errors": "last errors",
    "ui.health.no_errors": "no errors",
    "ui.health.since": "since",
    "ui.health.fix": "fix",
    "ui.health.version": "version",
    "ui.health.models": "by model today",
    "ui.spend.today": "today",
    "ui.spend.month": "this month",
    "ui.spend.cap": "cap",
    "ui.spend.no_cap": "no cap",
    "ui.spend.blocked": "paid calls paused",
    "ui.cua.absent": "not installed",
    "ui.cua.installed_not_running": "installed, not running",
    "ui.cua.socket_unresponsive": "not responding",
    "ui.cua.running": "running",
    "ui.cua.version_mismatch": "wrong version",
    "ui.cua.kill_switch_on": "kill switch on",
    "ui.cua.dry_run": "dry run",
    "ui.cua.unknown": "not checked yet",
    "ui.manage.home": "home",
    "ui.manage.activity": "activity",
    "ui.manage.memory": "memory",
    "ui.manage.agents": "agents",
    "ui.manage.health": "health",
    "ui.manage.spend": "spend",
    "ui.manage.audit": "audit",
    "ui.manage.binds": "binds",
    "ui.manage.settings": "settings",
    "ui.manage.spend.sub": "usage ledger, caps and paid calls",
    "ui.manage.spend.calls": "calls",
    "ui.manage.spend.tokens": "tokens",
    "ui.manage.spend.none": "no paid calls today",
    "ui.manage.audit.sub": "one row per guarded cua call. Typed text is never stored.",
    "ui.manage.audit.none": "no guarded calls yet",
    "ui.manage.audit.dry": "dry run",
    "ui.manage.audit.allow": "allowed",
    "ui.manage.audit.deny": "refused",
    "ui.manage.audit.dry_run": "dry run",
    "ui.manage.audit.cancelled": "stopped",
    "ui.manage.binds.sub": "hotkey and the Hyprland binds wisp registered",
    "ui.manage.binds.hold": "hold to talk",
    "ui.manage.binds.global": "global",
    "ui.manage.binds.submap": "submap",
    "ui.manage.binds.no_submap": "submap not installed",
    "ui.manage.binds.none": "no wisp binds registered",
    "ui.manage.binds.no_hypr": "Hyprland is not reachable",
    "ui.bar.ok": "ok",
    "ui.bar.down": "down",
    "ui.bar.spend": "today",
    "ui.bar.turns": "turns",
    "ui.bar.turn": "turn",
    "ui.bar.voice": "voice",
    "ui.bar.state.listening": "listening",
    "ui.bar.state.thinking": "thinking",
    "ui.bar.state.speaking": "speaking",
    "ui.bar.state.acting": "acting",
    "ui.bar.state.needs": "needs you",
    "ui.bar.state.error": "error",
    "ui.bar.state.done": "done",
    "ui.bar.hint": "click talk \u00b7 middle stop \u00b7 right panel",
    "ui.bar.hint.offline": "click: start wisp, right: open",
    "ui.confirm.title": "needs your ok",
    "ui.confirm.allow": "allow",
    "ui.confirm.deny": "deny",
    "ui.confirm.done": "done",
    "ui.confirm.cancel": "cancel",
    "ui.confirm.hint": "no answer counts as deny",
    "ui.err.format": "that does not look right",
    "set.cat.voice": "voice",
    "set.cat.pointer": "pointer",
    "set.cat.agents": "agents",
    "set.cat.models": "models",
    "set.cat.budget": "budget",
    "set.cat.connectors": "connectors",
    "set.cat.advanced": "advanced",
    "set.hotkey.mod.label": "talk key modifier",
    "set.hotkey.mod.help": "The modifier for the talk key, such as SUPER or ALT. Run wispd install after changing it to rebind.",
    "set.hotkey.key.label": "talk key",
    "set.hotkey.key.help": "The key you hold with the modifier to talk. Run wispd install after changing it to rebind.",
    "set.budget.daily_usd.help": "The most Wisp may spend on paid models in one day. Leave it blank for no cap.",
    "set.budget.monthly_usd.help": "The most Wisp may spend on paid models in one month. Leave it blank for no cap.",
    "set.budget.gate_primary.label": "stop the main model at the cap",
    "set.budget.gate_primary.help": "Also stop your main paid model at the cap, not only the fallbacks.",
    "set.pointer.mode.help": "Guide points at things, drive clicks for you, auto does either as the task needs.",
    "set.pointer.backend.label": "click backend",
    "set.pointer.backend.help": "The tool that sends clicks when Wisp drives. Auto picks one that works.",
    "set.cua.dry_run.help": "Plan and log every action without doing it. Good for trying a task safely.",
    "set.cua.kill_switch.help": "Refuse every click, key press and scroll Wisp would send.",
    "set.cua.confirm.help": "Ask before risky actions only, or before every action.",
    "set.cua.delivery.help": "Auto works in the background where it can. Background never touches your real cursor. Pointer prefers it.",
    "set.cua.max_clicks_per_min.help": "The most clicks Wisp may send in one minute.",
    "set.cua.max_per_turn.help": "The most actions Wisp may take in one turn.",
    "set.agent.autonomy.help": "Autonomous runs safe steps freely. Guided asks on those too. Always ask confirms everything.",
    "set.dictation.mode.help": "Raw types what you said. Cleanup fixes grammar. Compose writes finished text from your idea.",
    "set.cua.timeout_ms.label": "driver timeout",
    "set.cua.timeout_ms.help": "How long a click driver call may take before Wisp gives up, in milliseconds.",
    "set.audio.seconds.label": "longest recording",
    "set.audio.seconds.help": "The longest one recording may run, in seconds.",
    "set.chips.enabled.label": "ask chips",
    "set.chips.enabled.help": "Offer suggested questions when you tap the talk key without speaking. First week only.",
    "set.chips.days.label": "ask chip days",
    "set.chips.days.help": "How many days after your first tap the suggested questions are offered.",
    "set.agent.screenshots.label": "screenshots with answers",
    "set.agent.screenshots.help": "Attach a screenshot when Wisp answers a question about your screen.",
    "set.ui.theme.label": "fallback theme",
    "set.ui.theme.help": "The theme to use when your desktop theme cannot be read.",
    "set.brain.router.label": "turn routing",
    "set.brain.router.help": "How a turn is handled: act runs quick actions then the agent, chat only answers, off asks you to choose.",
    "set.brain.default.label": "answer model",
    "set.brain.default.help": "The model that answers you, as name:model. Hosted OpenRouter is the default. Local models such as ollama:name are supported.",
    "set.brain.fallback.label": "fallback models",
    "set.brain.fallback.help": "Models to try if the answer model fails, as name:model separated by commas. Leave blank for none.",
    "set.brain.first_token_s.label": "model start time",
    "set.brain.first_token_s.help": "How long a model has to start answering before Wisp tries the next one, in seconds.",
    "set.brain.agent_runtime.label": "agent runtime",
    "set.brain.agent_runtime.help": "The program that runs background agents. Auto uses the first one found.",
    "set.growth.weekly_recap.label": "weekly recap",
    "set.growth.weekly_recap.help": "Show a recap of last week once a week. It is built on this machine and nothing is sent.",
    "set.brain.allow_paid.label": "allow paid fallbacks",
    "set.brain.allow_paid.help": "Let the fallback list use paid models. Paid fallbacks are skipped when this is off.",
    "set.local.enabled.label": "local model servers",
    "set.local.enabled.help": "Allow local model servers such as llama.cpp and ollama. Hosted models keep working either way.",
    "set.keys.submap.label": "keys while a turn runs",
    "set.keys.submap.help": "Esc stops, Enter confirms and number keys choose while a turn is running.",
    "set.agents.act_max_steps.label": "tool calls per run",
    "set.agents.act_max_steps.help": "The most tool calls one agent run may make before it stops.",
    "set.agents.act_max_errors.label": "failed calls allowed",
    "set.agents.act_max_errors.help": "How many failed tool calls in a row an agent run tolerates.",
    "set.agents.act_max_parse_misses.label": "bad replies allowed",
    "set.agents.act_max_parse_misses.help": "How many unreadable replies an agent run tolerates in text mode.",
    "set.agents.act_max_seconds.label": "time per run",
    "set.agents.act_max_seconds.help": "The longest one agent run may take, in seconds. Zero means no limit.",
    "set.agents.act_max_usd.label": "spend per run",
    "set.agents.act_max_usd.help": "The most one agent run may spend on models, in USD. Zero means no limit.",
    "set.agents.writer_queue_max.label": "write queue size",
    "set.agents.writer_queue_max.help": "How many history writes wait in memory before the oldest is dropped.",
    "set.voice.captions.help": "Show the answer text in the bubble while it is spoken.",
    "set.voice.enabled.help": "Spoken answers: auto speaks when a voice is available, true always, false never.",
    "set.voice.provider.label": "voice engine",
    "set.voice.provider.help": "Who speaks: groq for hosted voices, or espeak to keep speech on this machine.",
    "set.voice.tts_voice.help": "Which hosted voice speaks your answers.",
    "set.quiet.on_calls.label": "quiet during calls",
    "set.quiet.on_calls.help": "Hold unprompted announcements while a call or screen share is on.",
    "set.browser.lane.label": "browser lane",
    "set.browser.lane.help": "Off, or extension to work in a tab group in your own browser through the Wisp extension.",
    "set.browser.port.label": "browser extension port",
    "set.browser.port.help": "The local port the Wisp browser extension connects to.",
    "set.stt.provider.label": "speech to text",
    "set.stt.provider.help": "Speech to text: an OpenAI-compatible service, or local whisper.cpp.",
    "set.packs.keep.label": "capture packs kept",
    "set.packs.keep.help": "How many of the newest capture packs to keep. Zero turns the count limit off.",
    "set.packs.keep_days.label": "capture pack days",
    "set.packs.keep_days.help": "How many days to keep a capture pack. Zero turns the age limit off.",
    "set.packs.shots_keep.label": "screenshots kept",
    "set.packs.shots_keep.help": "How many of the newest screenshots to keep. Zero turns the count limit off.",
    "set.packs.shots_keep_days.label": "screenshot days",
    "set.packs.shots_keep_days.help": "How many days to keep a screenshot. Zero turns the age limit off.",
    "set.dev.panel.label": "dev tab",
    "set.dev.panel.help": "Show the Dev tab with the gate, recent turns and stage timings. For developers only.",
    "set.dev.judge_cap_usd.label": "dev judging cap",
    "set.dev.judge_cap_usd.help": "The most one dev run may spend on judging its tasks, in USD.",
    "set.verify.judge_timeout_s.label": "verify judge time",
    "set.verify.judge_timeout_s.help": "How long the verify judge may take before a step counts as unverified, in seconds.",
    "set.verify.pixel_eps.label": "verify pixel tolerance",
    "set.verify.pixel_eps.help": "How much a pixel channel must change before the verify check counts it as changed.",
    "set.verify.region_px.label": "verify region size",
    "set.verify.region_px.help": "The side of the square screen region the verify check inspects around a click, in pixels.",
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


# statuses in which the daemon must keep publishing (the reader's BUSY
# set, shell-plugin/lib/state.js); a stale flag only means something here
BUSY = ("transcribing", "deciding", "acting")


def word_view(status: str, result: str = "", code: str = "",
              stale: bool = False) -> tuple:
    """(word, tone) every surface shows for the live state (pill, console
    status line, bar tooltip). One precedence, so no surface can disagree:
      - a busy turn whose state stopped updating reads `reconnecting`
        (muted), never the live word it can no longer vouch for;
      - an `error` turn with a code reads that code's message (fail);
      - a `done` turn whose result is BLOCKED reads `blocked` (needsYou),
        never `done` (the action did not happen);
      - anything else is the status word and tone.
    Offline is the `offline` status, which has its own word."""
    if stale and status in BUSY:
        return (STRINGS["state.reconnecting"], "muted")
    if status == "error" and code:
        return (error_message(code), "fail")
    if status == "done" and _BLOCKED.match(result or ""):
        return (STRINGS["ui.pill.blocked"], "needsYou")
    return (status_word(status), status_tone(status))


def pill_view(status: str, result: str = "") -> tuple:
    """`word_view` without a code or stale flag (kept for callers that
    only know status and result)."""
    return word_view(status, result)


def toast_text(code: str) -> str:
    """Notification body for an error code: the same message and hint
    every other surface shows, on two lines."""
    msg, hint = ERRORS.get(code, ERRORS[UNKNOWN_ERROR])
    return msg + ("\n" + hint if hint else "")


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
