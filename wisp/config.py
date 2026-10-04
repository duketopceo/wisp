"""Paths, config file, secrets, and the local harness catalog."""
import json
import os
import pathlib
import subprocess

HOME = pathlib.Path.home()
def _platform_dirs():
    from . import platform as _p
    return _p.dirs()

CFG_DIR, DATA_DIR_P, RUN_DIR_P = _platform_dirs()
CFG_FILE = CFG_DIR / "config.toml"
ENV_FILE = CFG_DIR / ".env"
DATA_DIR = pathlib.Path(
    os.environ.get("XDG_DATA_HOME", DATA_DIR_P.parent)) / "wisp"
CORRECTIONS = DATA_DIR / "corrections.jsonl"
DECISIONS = DATA_DIR / "decisions.jsonl"
_xdg_rt = os.environ.get("XDG_RUNTIME_DIR")
RUN_DIR = (pathlib.Path(_xdg_rt) / "wisp") if _xdg_rt else RUN_DIR_P
LEVEL_FILE = RUN_DIR / "level"
STATE_FILE = RUN_DIR / "state.json"
SOCK_FILE = RUN_DIR / "wispd.sock"
SESSION_FILE = DATA_DIR / "session.jsonl"
TASKS_FILE = DATA_DIR / "tasks.jsonl"
TASK_LOGS = DATA_DIR / "tasks"
HARNESS_FILE = CFG_DIR / "harness.json"
WHISPER_HOME = HOME / "src" / "whisper.cpp"
WHISPER_BIN = WHISPER_HOME / "build" / "bin" / "whisper-cli"

JEV_ENDPOINT = os.environ.get(
    "WISP_JEV_ENDPOINT", "https://openrouter.ai/api/alpha/decisions")
CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_CONFIG = """\
[hotkey]
# Super + D = push-to-talk. mod is a Hyprland modmask token (SUPER, ALT,
# SHIFT, CTRL) or a keysym like ALT_R (multi-key bind, side-specific).
mod = "SUPER"
key = "D"

[audio]
seconds = 60
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
# Numeric risk gate — Jev scores ~0-2 but overshoots (a launch scored
# 1.6). Default 9 sits above the band: effectively only extreme risk
# blocks. Real protection is the denylist + allow_shell + confirm tier.
risk_threshold = 9
confidence_instant = 0.95
confidence_ambiguous = 0.8
# runaway guards: max simultaneous agent tasks + per-task lifetime
max_concurrent = 3
task_timeout_s = 1800

[sense]
# Passive activity sense + proactive suggestions. Off by default —
# opt in. Sources are local: hyprctl window deltas + dayflow journal.
enabled = false
interval_s = 300
window_h = 3
# pull `dayflow today --json` block tail every Nth tick
dayflow = true
dayflow_every = 4
# mining cadence + spend cap; model is any "provider:model" the brain
# supports — e.g. ollama:gemma3:27b for zero-marginal-cost local mining
mine_every_s = 2700
max_calls_per_day = 48
model = "openrouter:google/gemini-2.5-flash"

[pointer]
# guide = Wisp points with the ghost cursor, you click (safe default).
# drive = inject real clicks via the detected backend.
# auto  = drive when a backend exists, guide otherwise.
mode = "guide"
# auto | ydotool | wlrctl | none — auto probes PATH (ydotool needs
# ydotoold + /dev/uinput; wlrctl needs wlroots virtual-pointer).
backend = "auto"

[traj]
# episodic memory for the act loop: every run is recorded and similar
# prior runs (paths + wrong branches) are injected as context.
enabled = true
max_inject = 3

[agents]
# coding-agent runtime overrides ([agent] is the Jev router section)
act_max_steps = 12

[dev]
# refinement loop: a labeled-bad turn or a correction cue ("no",
# "didn't work", "instead") makes the next utterance retry with the
# failed attempt as context; pairs are measured via wispd fails.
refine = true

[ui]
# orb/overlay theme: dark | light (wispd theme <name> swaps live)
theme = "dark"

[stt]
# Speech-to-text backend. "local" = whisper.cpp (default, offline).
# "openai" = any OpenAI-compatible /audio/transcriptions endpoint —
# Groq (base_url https://api.groq.com/openai/v1, model
# whisper-large-v3-turbo), OpenAI, vLLM, Together, DeepInfra.
provider = "local"
base_url = "https://api.groq.com/openai/v1"
model = "whisper-large-v3-turbo"
# name of the env var / .env key holding the API key
key_env = "GROQ_API_KEY"
# vocabulary priming — project names, jargon; whisper.cpp --prompt /
# `prompt` param on the openai provider (huge accuracy win on names)
prompt = "Wisp, wispd, Omarchy, Hyprland, Jev, OpenRouter, dayflow, omaseal, omarchy plugins, RetroArch, Steam, Discord, VS Code, Kubernetes, k8s, Tailscale, Waybar, Quickshell"

[recall]
# semantic recall via embeddings: "none" = FTS5 only (zero keys needed).
# provider = "openai" uses any OpenAI-compatible /embeddings endpoint —
# OpenRouter default below; model dims are auto-detected on first write.
provider = "none"
base_url = "https://openrouter.ai/api/v1"
model = "openai/text-embedding-3-small"
key_env = "OPENROUTER_API_KEY"

[brain]
# router: "jev" (typed decisions), "chat" (transcript+screen straight
# to the answer brain), or "off" (always clarify via choices)
router = "jev"
# answer provider as "name:model" — named sections below or any
# [brain.<name>] table you add (kind: openai_compat | ollama)
default = "openrouter:meta-llama/llama-4-maverick"
# fallback chain tried after `default`, comma-separated name:model.
# Paid entries (openrouter, or paid = "true" on the section) are skipped
# unless allow_paid = "true". Example: "mlx:ornith, ollama:ornith"
fallback = ""
allow_paid = "false"
# an entry must stream its first token within this many seconds or the
# chain moves on (a cold 21 GB model must not leave the turn stuck)
first_token_s = "3"
# background agent runtime: "auto" (probe PATH, opencode first) or an
# explicit opencode | codex | claude | devin
agent_runtime = "auto"

# Built-in provider sections — override or add [brain.<name>] tables.
[brain.openrouter]
kind = "openai_compat"
base_url = "https://openrouter.ai/api/v1"
key_env = "OPENROUTER_API_KEY"
vision = "true"
tools = "true"

[brain.ollama]
kind = "ollama"          # native /api/chat
base_url = "http://localhost:11434"
vision = "false"
tools = "false"

[brain.lmstudio]
kind = "openai_compat"
base_url = "http://localhost:1234/v1"
vision = "false"
tools = "false"

[brain.mlx]
kind = "openai_compat"   # mlx-lm server, probed on /v1/models
base_url = "http://localhost:8080/v1"
vision = "false"
tools = "false"

[health]
# probes of LOCAL endpoints (Jev, brain chain, optional extras); remote
# endpoints are never probed. Results ride state.json `health`.
enabled = "true"
interval_s = "30"      # idle probe period
press_stale_s = "10"   # on hotkey press, re-probe anything older
timeout_ms = "500"
# optional extra endpoints to watch:
# ollama = "http://127.0.0.1:11434"
# uitars = "http://127.0.0.1:8081"
# `wispd models start [--run]`: user units behind each endpoint name
# [health.units]
# jev = "llama-jev,jev-shim"
# brain_mlx = "llama-local"
# uitars = "llama-uitars"

[debug]
# full-fidelity event stream to ~/.local/share/wisp/trace.jsonl —
# every stage of every turn (record/stt/decision/tools/brain/tts/ipc)
# with ms timings, for replay-by-us-and-Jev debugging. Never logs keys.
trace = true

[voice]
# spoken replies via espeak/espeak-ng when true; missing binary = silent no-op
enabled = false
# custom TTS command (e.g. piper); `{text}` is replaced with the message,
# otherwise the message is appended as the last arg. Empty = espeak default.
cmd = ""

"""


# Per-OS default app map. These are the names Jev resolves "open the
# terminal" against, so a Linux name on macOS turns every such request
# into a SKIP. The live catalog (tools/adapters.py) supplies the rest.
_DEFAULT_APPS = {
    "linux": {
        "browser": "chromium", "terminal": "ghostty", "files": "nautilus",
        "vscode": "code", "music": "spotify",
        "settings": "gnome-control-center", "browser_new_tab": "chromium",
    },
    "macos": {
        # macOS values are launch *commands*, not bare names: desktop
        # .launch() probes which(value.split()[0]), and `Terminal` is not
        # on PATH while `open` is. The app name is single-quoted because
        # load_config() strips surrounding double quotes from TOML values
        # and would eat an inner closing quote.
        "browser": "open -a 'Safari'",
        "terminal": "open -a 'Terminal'",
        "files": "open -a 'Finder'",
        "vscode": "open -a 'Cursor'",
        "music": "open -a 'Spotify'",
        "settings": "open -a 'System Settings'",
        "browser_new_tab": "open -a 'Safari'",
    },
    "windows": {
        # cmdline for platform.launch_exec_cmds, which wraps these in
        # `cmd /c start "" /b <cmdline>`.
        "browser": "msedge", "terminal": "wt", "files": "explorer",
        "vscode": "code", "music": "spotify",
        "settings": "ms-settings:", "browser_new_tab": "msedge",
    },
}


def _host_os() -> str:
    """Host OS name; 'linux' when the platform seam is unavailable."""
    try:
        from . import platform
        return platform.current()
    except Exception:
        return "linux"


def _default_apps() -> dict:
    return dict(_DEFAULT_APPS.get(_host_os(), _DEFAULT_APPS["linux"]))


def _apps_toml() -> str:
    """The [apps] block rendered for this host."""
    return "[apps]\n" + "".join(
        f'{k} = "{v}"\n' for k, v in _default_apps().items())


def _default_cfg_dict() -> dict:
    return {
        "hotkey": {"mod": "SUPER", "key": "D"},
        "audio": {"seconds": "60", "whisper_model": "ggml-small.en.bin"},
        "agent": {
            "model": "typesafe/jev-1.13",
            "answer_model": "meta-llama/llama-4-maverick",
            "session_turns": "8", "screenshots": "true",
            "risk_threshold": "9",
            "confidence_instant": "0.95", "confidence_ambiguous": "0.8",
        },
        "voice": {"enabled": "false"},
        "pointer": {"mode": "guide", "backend": "auto"},
        "traj": {"enabled": "true", "max_inject": "3"},
        "agents": {"act_max_steps": "12"},
        "dev": {"refine": "true"},
        "ui": {"theme": "dark"},
        "brain": {
            "router": "jev", "agent_runtime": "auto",
            "default": "openrouter:meta-llama/llama-4-maverick",
            "fallback": "", "allow_paid": "false", "first_token_s": "3",
        },
        "health": {"enabled": "true", "interval_s": "30",
                   "press_stale_s": "10", "timeout_ms": "500"},
        "apps": _default_apps(),
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
        CFG_FILE.write_text(DEFAULT_CONFIG + _apps_toml())
        cfg = _default_cfg_dict()
    return cfg


def whisper_model(cfg: dict) -> pathlib.Path:
    name = cfg.get("audio", {}).get("whisper_model", "ggml-small.en.bin")
    return WHISPER_HOME / "models" / name


def load_env_key(name: str) -> str:
    """Resolve a secret: omaseal:// ref, .env file, then environment."""
    if name.startswith("omaseal://"):
        ref = name[len("omaseal://"):].split("/", 1)
        if len(ref) == 2:
            try:
                r = subprocess.run(
                    ["omaseal", "get", ref[0], ref[1]],
                    capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    return r.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        return ""
    v = os.environ.get(name, "")
    if v:
        return v
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return ""


def load_api_key() -> str:
    key = load_env_key("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(f"No OPENROUTER_API_KEY in {ENV_FILE} or environment")
    return key


def load_harness() -> dict | None:
    """Local personalization built by scripts/build_harness.py.
    Never committed — lives in ~/.config/wisp/."""
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
    # section may be nested ("brain.ollama"); key stays a bare name
    for part, pat in ((section, r"[A-Za-z0-9_.-]+"),
                      (key, r"[A-Za-z0-9_-]+")):
        if not _re.fullmatch(pat, part or ""):
            raise ValueError("config section/key must match "
                             "[A-Za-z0-9_.-]+ / [A-Za-z0-9_-]+")
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    if not CFG_FILE.exists():
        CFG_FILE.write_text(DEFAULT_CONFIG + _apps_toml())
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
