"""Paths, config file, secrets, and the local harness catalog."""
import json
import os
import pathlib

HOME = pathlib.Path.home()
CFG_DIR = HOME / ".config" / "dim-agent"
CFG_FILE = CFG_DIR / "config.toml"
ENV_FILE = CFG_DIR / ".env"
DATA_DIR = pathlib.Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share")) / "dim-agent"
CORRECTIONS = DATA_DIR / "corrections.jsonl"
DECISIONS = DATA_DIR / "decisions.jsonl"
RUN_DIR = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "dim-agent"
LEVEL_FILE = RUN_DIR / "level"
STATE_FILE = RUN_DIR / "state.json"
SOCK_FILE = RUN_DIR / "dimd.sock"
SESSION_FILE = DATA_DIR / "session.jsonl"
TASKS_FILE = DATA_DIR / "tasks.jsonl"
TASK_LOGS = DATA_DIR / "tasks"
HARNESS_FILE = CFG_DIR / "harness.json"
WHISPER_HOME = HOME / "src" / "whisper.cpp"
WHISPER_BIN = WHISPER_HOME / "build" / "bin" / "whisper-cli"

JEV_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_CONFIG = """\
[hotkey]
# Super + D = push-to-talk. mod is a Hyprland modmask token (SUPER, ALT,
# SHIFT, CTRL) or a keysym like ALT_R (multi-key bind, side-specific).
mod = "SUPER"
key = "D"

[audio]
seconds = 5
# whisper.cpp model filename under ~/src/whisper.cpp/models/
whisper_model = "ggml-small.en.bin"

[agent]
model = "typesafe/jev-1.13"
# OpenRouter chat model for the answer route — must accept image_url
# content parts (vision-capable) for screen-aware answers.
answer_model = "meta-llama/llama-4-maverick"
# number of prior turns fed back as context for follow-ups
session_turns = 8
# attach a screenshot to answer-route calls when true
screenshots = true
# Auto-execute when risk <= threshold. Measured Jev scores: "open terminal"
# launch scores ~1.2 (navigational band), so 1.5 = launch/close allowed,
# mutating (>=2) always requires explicit confirmation.
risk_threshold = 1.5
confidence_instant = 0.95
confidence_ambiguous = 0.8

[voice]
# spoken replies via espeak/espeak-ng when true; missing binary = silent no-op
enabled = false
# custom TTS command (e.g. piper); `{text}` is replaced with the message,
# otherwise the message is appended as the last arg. Empty = espeak default.
cmd = ""

[apps]
browser = "chromium"
terminal = "ghostty"
files = "nautilus"
vscode = "code"
music = "spotify"
settings = "gnome-control-center"
browser_new_tab = "chromium"
"""


def _default_cfg_dict() -> dict:
    return {
        "hotkey": {"mod": "SUPER", "key": "D"},
        "audio": {"seconds": "5", "whisper_model": "ggml-small.en.bin"},
        "agent": {
            "model": "typesafe/jev-1.13",
            "answer_model": "meta-llama/llama-4-maverick",
            "session_turns": "8", "screenshots": "true",
            "risk_threshold": "1.5",
            "confidence_instant": "0.95", "confidence_ambiguous": "0.8",
        },
        "voice": {"enabled": "false"},
        "apps": {
            "browser": "chromium", "terminal": "ghostty", "files": "nautilus",
            "vscode": "code", "music": "spotify",
            "settings": "gnome-control-center", "browser_new_tab": "chromium",
        },
    }


def load_config() -> dict:
    """Parse a flat [section] key = "value" TOML subset without deps."""
    cfg = {}
    if CFG_FILE.exists():
        section = None
        for raw in CFG_FILE.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("["):
                section = line.strip("[]")
                cfg[section] = {}
            elif "=" in line and section:
                k, v = (p.strip() for p in line.split("=", 1))
                cfg[section][k] = v.strip('"')
    else:
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        CFG_FILE.write_text(DEFAULT_CONFIG)
        cfg = _default_cfg_dict()
    return cfg


def whisper_model(cfg: dict) -> pathlib.Path:
    name = cfg.get("audio", {}).get("whisper_model", "ggml-small.en.bin")
    return WHISPER_HOME / "models" / name


def load_api_key() -> str:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError(f"No OPENROUTER_API_KEY in {ENV_FILE} or environment")
    return key


def load_harness() -> dict | None:
    """Local personalization built by scripts/build_harness.py.
    Never committed — lives in ~/.config/dim-agent/."""
    try:
        return json.loads(HARNESS_FILE.read_text())
    except Exception:
        return None


def set_config(section: str, key: str, value: str) -> None:
    """Update one key in config.toml, preserving comments and order.
    Appends the key under its section (or a new section) when absent.
    The flat parser can't represent quotes/backslashes/comments inside a
    value — reject them rather than writing corrupt TOML."""
    if any(c in value for c in '"\\#\n'):
        raise ValueError("config values may not contain \" \\ # or newline")
    import re as _re
    for part in (section, key):
        if not _re.fullmatch(r"[A-Za-z0-9_-]+", part or ""):
            raise ValueError("config section/key must match [A-Za-z0-9_-]+")
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    if not CFG_FILE.exists():
        CFG_FILE.write_text(DEFAULT_CONFIG)
    lines = CFG_FILE.read_text().splitlines()
    cur_section = None
    section_start = section_end = None
    written = False
    for i, raw in enumerate(lines):
        line = raw.split("#", 1)[0].strip()
        if line.startswith("["):
            if cur_section == section:
                section_end = i
            cur_section = line.strip("[]")
            if cur_section == section:
                section_start = i
            continue
        if cur_section == section and "=" in line:
            k = line.split("=", 1)[0].strip()
            if k == key:
                lines[i] = f'{key} = "{value}"'
                written = True
    if not written:
        if section_start is None:
            lines += ["", f"[{section}]", f'{key} = "{value}"']
        else:
            at = section_end if section_end is not None else len(lines)
            lines.insert(at, f'{key} = "{value}"')
    tmp = CFG_FILE.with_suffix(".toml.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(CFG_FILE)  # atomic — a crash can't truncate the config
