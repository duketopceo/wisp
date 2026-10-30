"""The settings schema (W28): one table for every surface.

Each field is declared once: key, kind, default, range or choices,
description, section and the widget the Panel draws for it. From that
table come

  - `wispd config set --help` / `wispd config keys` (help_table, as_dict),
  - the daemon-side check in config.set_config (problem, message),
  - shell-plugin/lib/settings_schema.js, written by
    scripts/assets/gen_settings.py (the Panel field table and validators).

tests/test_settings_schema.py fails when any of them drifts. Keys that are
not in the table (provider sections, apps) stay writable: only the
characters TOML cannot hold are refused for them.

Values are strings, as config.toml stores them. Kinds:
  usd     non-negative decimal, blank means no cap
  int     whole number inside [min, max]
  bool    "true" or "false"
  choice  one of `choices`
"""
import dataclasses
import re

# characters the flat TOML writer cannot hold inside a value
BAD_CHARS = '"\\#\n'
USD_MAX = 100000

# problem codes; the Panel shows the copy string ui.err.<code>
ERROR_CODES = ("unknown", "chars", "number", "range", "choice")

_WIDGET = {"usd": "number", "int": "number", "bool": "toggle",
           "choice": "choice"}


@dataclasses.dataclass(frozen=True)
class Field:
    key: str
    kind: str
    default: str
    description: str
    section: str = ""
    min: int | None = None
    max: int | None = None
    choices: tuple = ()
    panel: bool = False          # shown in the Panel settings tab
    label: str = ""              # copy key for the Panel label

    def __post_init__(self):
        object.__setattr__(self, "section", self.key.split(".")[0])

    @property
    def widget(self) -> str:
        return _WIDGET[self.kind]

    def range_text(self) -> str:
        if self.kind == "usd":
            return f"0 to {USD_MAX}, blank for no cap"
        if self.kind == "int":
            return f"{self.min} to {self.max}"
        if self.kind == "bool":
            return "true or false"
        return ", ".join(self.choices)

    def as_dict(self) -> dict:
        return {"key": self.key, "kind": self.kind, "default": self.default,
                "description": self.description, "section": self.section,
                "widget": self.widget, "min": self.min, "max": self.max,
                "choices": list(self.choices), "panel": self.panel}

    def panel_dict(self) -> dict:
        """The Panel field row (the shape lib/settings.js always had)."""
        d = {"key": self.key, "group": self.section, "kind": self.kind,
             "label": self.label, "widget": self.widget}
        if self.kind == "int":
            d["min"], d["max"] = self.min, self.max
        if self.kind == "choice":
            d["options"] = list(self.choices)
        return d


def _f(key, kind, default, description, **kw):
    return Field(key, kind, default, description, **kw)


FIELDS = (
    _f("budget.daily_usd", "usd", "8.00",
       "Daily cap on paid model spend in USD",
       panel=True, label="ui.set.daily"),
    _f("budget.monthly_usd", "usd", "160.00",
       "Monthly cap on paid model spend in USD",
       panel=True, label="ui.set.monthly"),
    _f("budget.gate_primary", "bool", "false",
       "Also stop the primary paid model at the cap, not just fallbacks"),
    _f("pointer.mode", "choice", "auto",
       "guide points, drive clicks for you, auto does either",
       choices=("guide", "drive", "auto"), panel=True,
       label="ui.set.pointer"),
    _f("pointer.backend", "choice", "auto",
       "Which backend injects clicks when driving",
       choices=("auto", "cua", "hyprcursor", "ydotool", "wlrctl", "none")),
    _f("cua.dry_run", "bool", "false",
       "Plan and log every action without performing it",
       panel=True, label="ui.set.dry_run"),
    _f("cua.kill_switch", "bool", "false",
       "Refuse every injected click, key and scroll",
       panel=True, label="ui.set.kill"),
    _f("cua.confirm", "choice", "tier",
       "Confirm risky actions (tier) or every action (always)",
       choices=("tier", "always"), panel=True, label="ui.set.confirm"),
    _f("cua.delivery", "choice", "auto",
       "Input delivery: auto = background where possible, pointer "
       "escalation otherwise; background never touches the real "
       "cursor; pointer prefers it",
       choices=("auto", "background", "pointer"),
       panel=True, label="ui.set.delivery"),
    _f("cua.max_clicks_per_min", "int", "30",
       "Most clicks allowed in one minute", min=1, max=600,
       panel=True, label="ui.set.clicks"),
    _f("cua.max_per_turn", "int", "12",
       "Most actions allowed in one turn", min=1, max=200,
       panel=True, label="ui.set.per_turn"),
    _f("agent.autonomy", "choice", "autonomous",
       "Confirm policy: autonomous runs reversible steps free, guided "
       "asks on them too, always_ask confirms everything",
       choices=("autonomous", "guided", "always_ask"),
       panel=True, label="ui.set.autonomy"),
    _f("dictation.mode", "choice", "cleanup",
       "Dictate mode: raw is verbatim, cleanup fixes grammar, "
       "compose writes the finished text from your idea",
       choices=("raw", "cleanup", "compose"),
       panel=True, label="ui.set.dictation"),
    _f("cua.timeout_ms", "int", "800",
       "Per call timeout for the cua driver in ms",
       min=50, max=60000),
    _f("audio.seconds", "int", "60",
       "Longest recording for one turn in seconds", min=1, max=600),
    _f("chips.enabled", "bool", "true",
       "Show ask chips when you tap the talk key without speaking "
       "(first week only)"),
    _f("chips.days", "int", "7",
       "How many days from the first tap the ask chips are offered",
       min=1, max=365),
    _f("agent.screenshots", "bool", "true",
       "Attach a screenshot to answer calls"),
    _f("ui.theme", "choice", "dark",
       "Fallback theme when the desktop theme is unreadable",
       choices=("dark", "light")),
    _f("brain.router", "choice", "act",
       "How a turn is routed: act (local fast paths then act), chat or off",
       choices=("act", "chat", "off")),
    _f("growth.weekly_recap", "bool", "false",
       "Show last week's local days, turns and recorded spend once each week; nothing is sent",
       section="growth", panel=False),
    _f("brain.allow_paid", "bool", "false",
       "Let the fallback chain use paid models"),
    _f("local.enabled", "bool", "false",
       "Allow local model servers (llama.cpp, UI-TARS, jev-shim, ollama)"),
    _f("keys.submap", "bool", "true",
       "Esc stops, Enter confirms, number keys choose while a turn runs"),
    _f("agents.act_max_steps", "int", "12",
       "Most tool calls one act run may make before it aborts",
       min=1, max=100),
    _f("agents.act_max_errors", "int", "2",
       "Consecutive failed tool calls an act run tolerates",
       min=0, max=20),
    _f("agents.act_max_parse_misses", "int", "1",
       "Unparseable action replies tolerated in action text mode",
       min=0, max=10),
    _f("agents.act_max_seconds", "int", "600",
       "Wall-clock seconds one act run may take before it aborts "
       "(0 disables)",
       min=0, max=86400),
    _f("agents.act_max_usd", "usd", "0",
       "Per-run cap on model spend in USD added during the run "
       "(0 disables)"),
    _f("agents.writer_queue_max", "int", "256",
       "Trajectory and recall writes held in memory before the oldest "
       "is dropped",
       min=1, max=100000),
    _f("voice.captions", "bool", "true",
       "Show the answer text in the bubble while it is spoken (off: the "
       "voice is the answer; a muted speaker still shows it)",
       panel=True, label="ui.set.captions"),
    _f("voice.enabled", "choice", "auto",
       "Spoken answers: auto speaks when a Groq key or a local voice "
       "exists, true always, false never",
       choices=("auto", "true", "false"),
       panel=True, label="ui.set.voice"),
    _f("voice.provider", "choice", "groq",
       "Who speaks: groq (Orpheus, English; espeak or [voice] cmd when "
       "Groq cannot) or espeak (never ask Groq)",
       choices=("groq", "espeak")),
    _f("voice.tts_voice", "choice", "hannah",
       "Groq Orpheus voice",
       choices=("autumn", "diana", "hannah", "austin", "daniel", "troy"),
       panel=True, label="ui.set.tts_voice"),
    _f("quiet.on_calls", "bool", "true",
       "Hold announcements nobody asked for (a finished background "
       "agent) while a call or a screen share is on"),
    _f("browser.lane", "choice", "off",
       "Browser lane: off, or extension (work in a tab group in your own "
       "browser through the paired Wisp extension)",
       choices=("off", "extension")),
    _f("browser.port", "int", "47315",
       "Loopback port the Wisp browser extension polls", min=1024,
       max=65535),
    _f("stt.provider", "choice", "openai",
       "Speech to text: an OpenAI-compatible API or local whisper.cpp",
       choices=("openai", "local")),
    _f("packs.keep", "int", "200",
       "Newest capture packs retained under packs/ (0 disables the "
       "count bound)",
       min=0, max=100000),
    _f("packs.keep_days", "int", "30",
       "Days a capture pack is kept (0 disables the age bound)",
       min=0, max=3650),
    _f("packs.shots_keep", "int", "100",
       "Newest screenshots kept under shots/ (the pack writer owns "
       "its pruning; 0 disables the count bound)",
       min=0, max=100000),
    _f("packs.shots_keep_days", "int", "30",
       "Days a shots/ screenshot is kept (0 disables the age bound)",
       min=0, max=3650),
    _f("dev.panel", "bool", "false",
       "Show the Dev tab (gate, recent turns, stage timings) in the panel; "
       "local-only, off for everyone else"),
    _f("dev.judge_cap_usd", "usd", "1.00",
       "Most one dev run may spend on judging its tasks (the rest of the "
       "run is left unjudged at the cap)"),
    _f("verify.judge_timeout_s", "int", "20",
       "Seconds the verify VLM judge may take before the step lands "
       "unverifiable",
       min=1, max=300),
    _f("verify.pixel_eps", "int", "16",
       "Per-channel pixel difference the verify masked diff counts as "
       "a change",
       min=1, max=255),
    _f("verify.region_px", "int", "96",
       "Side of the square pixel region the verify diff inspects "
       "around a click point",
       min=8, max=1024),
)

_BY_KEY = {f.key: f for f in FIELDS}
KEYS = tuple(f.key for f in FIELDS)


def field(key: str) -> Field | None:
    return _BY_KEY.get(key)


def panel_fields() -> list:
    return [f for f in FIELDS if f.panel]


def problem(key: str, raw) -> str:
    """"" when `raw` may be written to `key`, else an error code from
    ERROR_CODES. A key outside the table only has its characters checked
    (so provider sections stay writable)."""
    v = "" if raw is None else str(raw).strip()
    if any(c in v for c in BAD_CHARS):
        return "chars"
    f = _BY_KEY.get(key)
    if f is None:
        return ""
    if f.kind == "usd":
        if v == "":
            return ""
        if not re.fullmatch(r"\d+(\.\d+)?", v):
            return "number"
        return "range" if float(v) > USD_MAX else ""
    if f.kind == "int":
        if not re.fullmatch(r"\d+", v):
            return "number"
        return "" if f.min <= int(v) <= f.max else "range"
    if f.kind == "bool":
        return "" if v in ("true", "false") else "choice"
    return "" if v in f.choices else "choice"


def message(key: str, raw) -> str:
    """The E_BAD_CONFIG sentence for a rejected value ("" when fine)."""
    code = problem(key, raw)
    if not code:
        return ""
    f = _BY_KEY.get(key)
    if code == "chars":
        return (f"{key} may not contain a quote, a backslash, # or a "
                "newline.")
    if code == "number":
        return f"{key} must be a plain number."
    if code == "range":
        if f.kind == "usd":
            return f"{key} must be between 0 and {USD_MAX}."
        return f"{key} must be between {f.min} and {f.max}."
    if f.kind == "bool":
        return f"{key} must be true or false."
    return f"{key} must be one of: {', '.join(f.choices)}."


def help_table() -> str:
    """The `wispd config keys` text, also appended to `config set --help`."""
    lines = ["Settings (value, default, range):"]
    width = max(len(f.key) for f in FIELDS)
    for f in FIELDS:
        lines.append(f"  {f.key:<{width}}  {f.description}")
        lines.append(f"  {'':<{width}}  default {f.default or 'blank'}; "
                     f"{f.range_text()}")
    return "\n".join(lines)
