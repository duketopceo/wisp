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
SHADOW = DATA_DIR / "shadow.jsonl"
ROUTE_AB = DATA_DIR / "route_ab.jsonl"
_xdg_rt = os.environ.get("XDG_RUNTIME_DIR")
RUN_DIR = (pathlib.Path(_xdg_rt) / "wisp") if _xdg_rt else RUN_DIR_P
LEVEL_FILE = RUN_DIR / "level"
STATE_FILE = RUN_DIR / "state.json"
SOCK_FILE = RUN_DIR / "wispd.sock"
SESSION_FILE = DATA_DIR / "session.jsonl"
TASKS_FILE = DATA_DIR / "tasks.jsonl"
TASK_LOGS = DATA_DIR / "tasks"
# Paper notes live under XDG_STATE_HOME (see wisp.note.notes_dir); this
# constant is the default Linux path for docs/callers that need a Path.
NOTES_DIR = pathlib.Path(
    os.environ.get("XDG_STATE_HOME",
                   str(pathlib.Path.home() / ".local" / "state"))) / "wisp" / "notes"
HARNESS_FILE = CFG_DIR / "harness.json"
WHISPER_HOME = HOME / "src" / "whisper.cpp"
WHISPER_BIN = WHISPER_HOME / "build" / "bin" / "whisper-cli"

JEV_ENDPOINT = os.environ.get(
    "WISP_JEV_ENDPOINT", "https://openrouter.ai/api/alpha/decisions")
CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# Second deciders, run alongside the primary purely to record agreement.
# Selected with `[jev] shadow = "<name>"`; the primary still decides every
# turn — a shadow never changes what the agent does, it only creates the
# labeled-comparison data the v1.0 accuracy gate needs. The pplx shadow
# uses OpenRouter (same key as Jev) — no separate Perplexity key.
SHADOW_PROVIDERS = {
    "pplx": {
        "endpoint": "https://openrouter.ai/api/alpha/decisions",
        "model": "perplexity/pplx-decider-v1.2",
        "key_env": "OPENROUTER_API_KEY",
    },
}

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
# autonomy mode for the act loop's confirm policy (wisp/policy.py):
# autonomous runs reversible steps free and batch-confirms irreversible
# ones; guided confirms reversible steps too; always_ask confirms all
autonomy = "autonomous"

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
# auto | cua | hyprcursor | ydotool | wlrctl | none — auto prefers a
# live cua-driver daemon (background virtual-pointer clicks on native
# Wayland — needs the cua-hyprland plugin + CUA_DRIVER_RS_ENABLE_WAYLAND=1
# on the daemon), then hyprcursor/ydotool, then wlrctl. A named backend
# is used alone: if it is unavailable wisp guides instead.
backend = "auto"

[keys]
# Keyboard submap while a turn acts or waits (wisp/keys.py): Esc stops,
# Enter confirms, number keys choose. "false" leaves the keyboard alone.
submap = "true"

[cua]
# cua-driver client (wisp/cua.py). Per-call timeout; a click that times
# out is reported as failed and never retried on another backend.
timeout_ms = "800"
# Safety layer (wisp/cua_safety.py) around every injected click/move/
# scroll/type/key. Built-in deny: password managers, polkit/pinentry
# prompts, terminals whose title shows sudo. allow/deny = comma lists of
# window-class substrings (deny wins; a set allow list fails closed).
safety = "true"
allow = ""
deny = ""
max_clicks_per_min = "30"
max_per_turn = "12"
dry_run = "false"
kill_switch = "false"
confirm = "tier"
audit = "true"
# Input delivery policy (wisp/delivery.py, U5): "auto" takes each op's
# natural channel — background where a no-cursor path exists (DOM/JS
# dispatch, cua virtual-pointer clicks, typing, wheel scrolls, Hyprland
# window ops), real-pointer escalation for pixel clicks/moves on
# ydotool-class backends. "background" never touches the real cursor —
# a pointer-only op degrades to the ghost cursor instead of injecting.
# "pointer" prefers the real pointer (auto order skips the
# background-only cua backend for clicks). The actual channel is
# recorded per call in the audit log and action stream.
delivery = "auto"

[ground]
# UI grounding adapter (wisp/grounding.py, W13): click/move target name ->
# screen point. Chain order; control = the app's own control channel
# (wisp/control.py — apps registered under [control], FilmCraft first),
# a11y = cua get_window_state tree (when the driver is up), uitars =
# local llama-server (loopback only, screenshots never leave the box),
# jev = the Decision-Agent patch fallback.
providers = "control,a11y,uitars,jev"
# candidates below this are re-observed once, then refused (never clicked)
min_confidence = "0.5"
# shared budget for the fast providers (P7: act first step 1.2 s)
budget_ms = "1200"
# the slow vision fallback gets its own timeout
fallback_timeout_ms = "5000"
# uitars_url = "http://127.0.0.1:8081"   # default: [health] uitars or this
# uitars_coords = "px"                    # px | rel1000
# a11y_frame = "global"                   # global | window (element frames)

# Per-app control channels (wisp/control.py, U3/KTD3): apps exposing a
# JSON-lines control port get ground-truth grounding + a corroborating
# verify rung. FilmCraft is built in at 127.0.0.1:9876 (launch it with
# `--control 9876`). Add another app's channel under [control]:
# [control]
#   myapp = "127.0.0.1:9877"            # host:port — loopback only
# or a table for port + optional host + class/title match patterns:
# [control.myapp]
# port = "9877"                         # host defaults to 127.0.0.1
# match = "myapp,My App"                # default: the app key
# connect_timeout_s / read_timeout_s under [control] bound the socket.

[traj]
# episodic memory for the act loop: every run is recorded and similar
# prior runs (paths + wrong branches) are injected as context.
enabled = true
max_inject = 3

[packs]
# Capture packs (wisp/packs.py, U4): one packs/<turn>/ dir per recorded
# act turn — manifest.json, frame PNGs, contact.png. Mode 0700;
# keyboard args persist only as a salted-HMAC hash. Retention keeps the
# newest `keep` packs AND drops any older than keep_days — both bounds
# apply, 0 disables that axis. The pack writer is also shots/'s pruning
# owner: the screenshot tool's files age out on the same count+age
# policy via shots_keep/shots_keep_days (set 0/0 to keep them forever).
keep = "200"
keep_days = "30"
shots_keep = "100"
shots_keep_days = "30"

[docs]
# Answer about the whole document (wisp/docread.py): the focused PDF,
# DOCX, XLSX, TXT or MD file is read locally and the relevant pages go
# to the answer. Never from protected folders; false turns it off.
enabled = "true"

[chips]
# "What can I ask here?" (wisp/chips.py): a quick tap of the talk key, with
# no speech, shows up to three asks that fit the focused app, for the first
# `days` days of use. Never without a tap. false turns them off.
enabled = "true"
days = "7"

[images]
# Image cards (wisp/tools/imagefetch.py): an answer may show one picture.
# Only https hosts in `allow` (a comma list; each entry also matches its
# subdomains) are fetched, never more than max_kb, never longer than
# timeout_s. Empty allow keeps the built-in default (Wikimedia's image host).
allow = ""
max_kb = "4096"
timeout_s = "8"

[verify]
# Verify ladder (wisp/verify.py, U2): each recorded action's verdict.
# The pixel rung masks a region_px square around the click point and
# diffs before/after at pixel_eps per-channel sensitivity —
# >=pixel_landed_min changed votes landed, <=pixel_missed_max votes
# missed, between them abstains to the judge. frame_wait_s bounds the
# wait for the driver's frames. The VLM judge resolves disagreements
# and bare 'effect' claims; vlm names a 'provider:model' endpoint
# (empty = primary brain), judge_timeout_s bounds it.
# vlm = ""
judge_timeout_s = "20"
pixel_landed_min = "0.02"
pixel_missed_max = "0.001"
pixel_eps = "16"
region_px = "96"
frame_wait_s = "0.5"

[agents]
# coding-agent runtime overrides (the router key lives in [brain])
act_max_steps = 12
act_max_errors = 2          # consecutive failed tool calls tolerated
act_max_parse_misses = 1    # unparseable replies in action-text mode
act_max_seconds = 600       # wall-clock bound per run; 0 disables
act_max_usd = 0             # per-run model-spend cap; 0 disables
routine_wait_s = 120        # a scheduled routine waits this long for the network
writer_queue_max = 256      # background trajectory/recall writes queued

[dev]
# refinement loop: a labeled-bad turn or a correction cue ("no",
# "didn't work", "instead") makes the next utterance retry with the
# failed attempt as context; pairs are measured via wispd fails.
refine = true

[eval]
# `wispd eval` gate: the first-time-correct fraction (0-1) the owner
# requires over at least gate_min_turns labelled turns. The owner set
# the v1 bar at 60% (2026-10-27).
gate_rate = "60%"
gate_min_turns = 50

[ui]
# orb/overlay theme: dark | light (wispd theme <name> swaps live)
theme = "dark"

[stt]
# Speech-to-text backend. "openai" = any OpenAI-compatible
# /audio/transcriptions endpoint (default) — Groq (base_url
# https://api.groq.com/openai/v1, model whisper-large-v3-turbo),
# OpenAI, vLLM, Together, DeepInfra. "local" = whisper.cpp (offline,
# opt-in: sh scripts/fetch_whisper.sh).
provider = "openai"
base_url = "https://api.groq.com/openai/v1"
model = "whisper-large-v3-turbo"
# env var / .env key holding the API key — comma list tries sources in
# order, e.g. "omaseal://groq/default,GROQ_API_KEY" (keyring first,
# plain env/.env fallback so non-omaseal installs still work)
key_env = "GROQ_API_KEY"

# vocabulary priming — project names, jargon; whisper.cpp --prompt /
# `prompt` param on the openai provider (huge accuracy win on names)
prompt = "Wisp, wispd, Omarchy, Hyprland, Jev, OpenRouter, dayflow, omaseal, omarchy plugins, RetroArch, Steam, Discord, VS Code, Kubernetes, k8s, Tailscale, Waybar, Quickshell"

[web]
# Web app a role opens when its default handler is a browser (a native
# client such as thunderbird is launched as usual). No '#' in a URL: the
# config parser reads it as a comment.
mail = "https://mail.google.com"
calendar = "https://calendar.google.com"

[dictation]
# what `dictate` does with the transcript: raw (verbatim), cleanup
# (grammar/spelling pass, words preserved), compose (ramble -> finished
# text in the focused app's genre). "dictate raw ..." overrides per
# call; "write an email ..." phrasing triggers compose.
mode = "cleanup"
# extra window classes that count as terminals for the newline guard
# (comma list; built-ins: foot, alacritty, kitty, ghostty, wezterm)
# terminal_classes = "cool-retro-term"
# model override for the cleanup/compose pass, "provider:model" like
# [brain] default — falls back to the brain chain when unset
# model = ""
# per-app profiles (VoiceInk-style Power Mode, thin): one section per
# class pattern, matched *pattern* against the focused window class
# [dictation.profiles.chromium]
# mode = "compose"
# style = "professional email"
# auto_send = false          # true asks before pressing Return

[recall]
# semantic recall via embeddings: "none" = FTS5 only (zero keys needed).
# provider = "openai" uses any OpenAI-compatible /embeddings endpoint —
# OpenRouter default below; model dims are auto-detected on first write.
provider = "none"
base_url = "https://openrouter.ai/api/v1"
model = "openai/text-embedding-3-small"
key_env = "OPENROUTER_API_KEY"

[budget]
# Paid-model spend caps in USD (usage ledger, wisp/ledger.py). At a cap,
# paid FALLBACK entries are refused; the primary brain still runs unless
# gate_primary = "true". Local models always keep working. Blank = no
# cap. Day and month roll over by local date.
# daily_usd unset = the legacy [brain] daily_cap_usd, else 8.00.
# daily_usd = "8.00"
monthly_usd = "160.00"
gate_primary = "false"

[brain]
# router: "act" (every turn straight to the agent loop — default),
# "jev" (typed decisions), "chat" (transcript+screen straight to the
# answer brain), or "off" (always clarify via choices)
router = "act"
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

[local]
# Local model servers (llama.cpp / ollama / UI-TARS) are opt-in. Off:
# onboarding skips the local ladder, grounding drops the uitars
# provider, and `wispd install --units` skips the llama/jev-shim units.
# Brains still come from [brain]; OpenRouter is the default.
enabled = "false"

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

# Local GPU models via llama.cpp Vulkan servers (uncomment to use).
# `wispd` reads these like any other brain provider.
# [brain.llama_local]
# kind = "openai_compat"   # Ornith-35B + mmproj on llama-server :8080
# base_url = "http://127.0.0.1:8080/v1"
# vision = "true"
# tools = "true"
# [brain.uitars]
# kind = "openai_compat"   # UI-TARS-7B on llama-server :8081 — emits
# base_url = "http://127.0.0.1:8081/v1"   # 'Action: click(x,y)' text
# vision = "true"                          # instead of tool_calls
# tools = "false"
# action_text = "true"
# Jev can also run locally: point WISP_JEV_ENDPOINT at a jev-shim
# (e.g. http://127.0.0.1:8931/decisions → llama-jev qwen3-4b :8091).

[jev]
# Shadow decider: a second decision model answers the same questions on
# every turn so the two can be compared against your labels later. The
# PRIMARY still decides — a shadow never changes what Wisp does, it only
# accumulates the agreement data the soak needs. Both answers land in
# shadow.jsonl, keyed by the same turn id decisions.jsonl carries. "" = off.
# Known values: "pplx" (perplexity/pplx-decider-v1.2 on OpenRouter).
shadow = ""
# Optional runtime route lane: flash decider before Jev (default off).
# flash_decider = false
# flash_model = "perplexity/pplx-decider-flash-v1.2"
# flash_confidence = 0.7
# flash_deadline_ms = 220   # sub-budget of deadline_ms; rest goes to Jev
# Jev is an accelerator, never a gate: past this many ms the heuristic
# router decides and the turn goes on (route_ab.jsonl keeps both).
# deadline_ms = 400

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

[notify]
# desktop toasts (D-Bus org.freedesktop.Notifications; notify-send fallback)
enabled = true
# silent window, may cross midnight; empty = never quiet
quiet = ""
# identical toasts inside this many seconds are dropped
dedupe_secs = 60
# toast expiry; buttons (Retry, Open log) only when the server supports them
timeout_ms = 5000
actions = true

[report]
# opt-in error reporting to GlitchTip (Sentry-compatible). Off while dsn
# is empty. dsn may be omaseal://svc/acct. Only typed error codes and a
# scrubbed context are sent: never transcripts, screenshots, typed text,
# paths with your username, env values or keys.
dsn = ""
per_code_per_hour = 3
global_per_hour = 20
dedupe_secs = 300
queue_max = 50

"""


# Default app map. These are the names Jev resolves "open the
# terminal" against. The live catalog (tools/adapters.py) supplies the rest.
_DEFAULT_APPS = {
    "linux": {
        "browser": "chromium", "terminal": "ghostty", "files": "nautilus",
        "vscode": "code", "music": "spotify",
        "settings": "gnome-control-center", "browser_new_tab": "chromium",
    },
}


def _default_apps() -> dict:
    return dict(_DEFAULT_APPS["linux"])


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
            "autonomy": "autonomous",
        },
        "voice": {"enabled": "false"},
        "dictation": {"mode": "cleanup"},
        "pointer": {"mode": "guide", "backend": "auto"},
        "cua": {"timeout_ms": "800", "safety": "true", "allow": "",
                "deny": "", "max_clicks_per_min": "30",
                "max_per_turn": "12", "dry_run": "false",
                "kill_switch": "false", "confirm": "tier",
                "audit": "true", "delivery": "auto"},
        "traj": {"enabled": "true", "max_inject": "3"},
        "packs": {"keep": "200", "keep_days": "30",
                  "shots_keep": "100", "shots_keep_days": "30"},
        "docs": {"enabled": "true"},
        "chips": {"enabled": "true", "days": "7"},
        "images": {"allow": "", "max_kb": "4096", "timeout_s": "8"},
        "verify": {"judge_timeout_s": "20", "pixel_landed_min": "0.02",
                   "pixel_missed_max": "0.001", "pixel_eps": "16",
                   "region_px": "96", "frame_wait_s": "0.5"},
        "agents": {"act_max_steps": "12", "act_max_errors": "2",
                   "act_max_parse_misses": "1", "act_max_seconds": "600",
                   "act_max_usd": "0", "routine_wait_s": "120",
                   "writer_queue_max": "256"},
        "dev": {"refine": "true"},
        "eval": {"gate_min_turns": "50"},
        "ui": {"theme": "dark"},
        "brain": {
            "router": "act", "agent_runtime": "auto",
            "default": "openrouter:meta-llama/llama-4-maverick",
            "fallback": "", "allow_paid": "false", "first_token_s": "3",
        },
        "budget": {"monthly_usd": "160.00", "gate_primary": "false"},
        "local": {"enabled": "false"},
        "health": {"enabled": "true", "interval_s": "30",
                   "press_stale_s": "10", "timeout_ms": "500"},
        "apps": _default_apps(),
    }


def load_config() -> dict:
    """Parse a flat [section] key = "value" TOML subset without deps."""
    cfg = {}
    if CFG_FILE.exists():
        section = None
        for raw in CFG_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
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
        CFG_FILE.write_text(DEFAULT_CONFIG + _apps_toml(), encoding="utf-8")
        cfg = _default_cfg_dict()
    return cfg


def local_enabled(cfg: dict | None) -> bool:
    """[local] enabled — local model servers are opt-in (default off)."""
    v = ((cfg or {}).get("local", {}) or {}).get("enabled", "false")
    return str(v).strip().lower() == "true"


def whisper_model(cfg: dict) -> pathlib.Path:
    name = cfg.get("audio", {}).get("whisper_model", "ggml-small.en.bin")
    return WHISPER_HOME / "models" / name


STT_DEFAULTS = {
    "provider": "openai",
    "base_url": "https://api.groq.com/openai/v1",
    "model": "whisper-large-v3-turbo",
    "key_env": "GROQ_API_KEY",
}


def stt_settings(cfg: dict | None) -> dict:
    """[stt] with the hosted defaults filled in under whatever the user
    set — load_config does not merge defaults into an existing file."""
    return {**STT_DEFAULTS, **((cfg or {}).get("stt") or {})}


WEB_DEFAULTS = {
    "mail": "https://mail.google.com",
    "calendar": "https://calendar.google.com",
}


def web_settings(cfg: dict | None) -> dict:
    """[web] role URLs with the defaults under whatever the user set —
    an empty value falls back too. load_config does not merge defaults
    into an existing file."""
    user = (cfg or {}).get("web") or {}
    return {**WEB_DEFAULTS,
            **{k: v for k, v in user.items() if str(v).strip()}}


# a keyring that is locked or wedged must not hang a turn
OMASEAL_TIMEOUT_S = 3


def key_label(name: str) -> str:
    """The name to show for a key_env list: its first plain env var
    (GROQ_API_KEY for `omaseal://groq/default,GROQ_API_KEY`), else the
    list itself."""
    cands = [c.strip() for c in str(name).split(",") if c.strip()]
    return next((c for c in cands if not c.startswith("omaseal://")),
                str(name))


def load_env_key(name: str) -> str:
    """Resolve a secret. `name` may be a comma-separated list of
    sources tried in order — `omaseal://svc/acct` refs and plain env
    var names (also looked up in .env) — so an omaseal user can keep
    `omaseal://groq/default,GROQ_API_KEY` and a non-omaseal install
    still resolves the same key. "" when nothing yields a value."""
    for cand in (c.strip() for c in str(name).split(",")):
        if not cand:
            continue
        if cand.startswith("omaseal://"):
            ref = cand[len("omaseal://"):].split("/", 1)
            if len(ref) == 2:
                try:
                    from . import platform as _platform
                    r = subprocess.run(
                        [_platform.resolve_exe("omaseal"), "get",
                         ref[0], ref[1]],
                        capture_output=True, text=True,
                        timeout=OMASEAL_TIMEOUT_S)
                    if r.returncode == 0 and r.stdout.strip():
                        return r.stdout.strip()
                except (OSError, subprocess.SubprocessError):
                    pass
            continue
        v = os.environ.get(cand, "")
        if v:
            return v
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text().splitlines():
                if line.startswith(f"{cand}="):
                    return line.split("=", 1)[1].strip()
    return ""


def require_key(name: str) -> str:
    """load_env_key for a key a turn cannot go on without: a miss raises
    the `key_missing` WispError naming the key and `wispd onboard`."""
    key = load_env_key(name)
    if not key:
        from . import errors_codes
        label = key_label(name)
        raise errors_codes.WispError(
            "key_missing", f"no {label} in {ENV_FILE} or environment",
            f"{label} is missing, run wispd onboard")
    return key


def load_api_key() -> str:
    return require_key("OPENROUTER_API_KEY")


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
    # keys in the settings schema (wisp/settings_schema.py) are also
    # checked for type and range, so every writer shares one rule
    from . import settings_schema
    bad = settings_schema.message(f"{section}.{key}", value)
    if bad:
        raise ValueError(bad)
    if settings_schema.field(f"{section}.{key}"):
        value = value.strip()
    import re as _re
    # section may be nested ("brain.ollama"); key stays a bare name
    for part, pat in ((section, r"[A-Za-z0-9_.-]+"),
                      (key, r"[A-Za-z0-9_-]+")):
        if not _re.fullmatch(pat, part or ""):
            raise ValueError("config section/key must match "
                             "[A-Za-z0-9_.-]+ / [A-Za-z0-9_-]+")
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    if not CFG_FILE.exists():
        CFG_FILE.write_text(DEFAULT_CONFIG + _apps_toml(),
                            encoding="utf-8")
    lines = CFG_FILE.read_text(encoding="utf-8").splitlines()
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
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(CFG_FILE)  # atomic — a crash can't truncate the config
