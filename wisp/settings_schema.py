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
    _f("budget.daily_usd", "usd", "2.00",
       "Daily cap on paid model spend in USD",
       panel=True, label="ui.set.daily"),
    _f("budget.monthly_usd", "usd", "20.00",
       "Monthly cap on paid model spend in USD",
       panel=True, label="ui.set.monthly"),
    _f("pointer.mode", "choice", "guide",
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
    _f("cua.max_clicks_per_min", "int", "30",
       "Most clicks allowed in one minute", min=1, max=600,
       panel=True, label="ui.set.clicks"),
    _f("cua.max_per_turn", "int", "12",
       "Most actions allowed in one turn", min=1, max=200,
       panel=True, label="ui.set.per_turn"),
    _f("cua.timeout_ms", "int", "800",
       "Per call timeout for the cua driver in ms",
       min=50, max=60000),
    _f("audio.seconds", "int", "60",
       "Longest recording for one turn in seconds", min=1, max=600),
    _f("agent.screenshots", "bool", "true",
       "Attach a screenshot to answer calls"),
    _f("ui.theme", "choice", "dark",
       "Fallback theme when the desktop theme is unreadable",
       choices=("dark", "light")),
    _f("brain.router", "choice", "jev",
       "How a turn is routed: jev, chat or off",
       choices=("jev", "chat", "off")),
    _f("brain.allow_paid", "bool", "false",
       "Let the fallback chain use paid models"),
    _f("keys.submap", "bool", "true",
       "Esc stops, Enter confirms, number keys choose while a turn runs"),
    _f("stt.provider", "choice", "local",
       "Speech to text: local whisper.cpp or an API",
       choices=("local", "openai")),
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
