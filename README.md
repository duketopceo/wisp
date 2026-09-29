# Wisp

**Wisp, open spotify.** — a resident voice assistant for Omarchy
(Hyprland). Press `Super+D`, speak, and Wisp hears, decides, and acts:
launch an app, run a desktop tool, spawn a coding agent, or just answer.

Push-to-talk → PipeWire mic capture → whisper.cpp → Jev routing
(OpenRouter) → risk-tiered toolbelt / `ori opencode` agents → widgets in
your Omarchy bar.

## Features

- **Resident daemon**: `wispd` runs as a systemd user service holding
  session, choice, and agent state on a unix socket. `Super+D` sends
  `listen`; the daemon owns the whole pipeline.
- **Jev routing**: each utterance is classified as `launch`, `tool`,
  `agent`, `answer`, or `clarify` — questions get text answers, not
  forced actions. The confidence gate keys on the *target* (app/tool)
  so a hesitant action score never cancels a correct launch.
- **Real answers**: the `answer` route calls an OpenRouter chat model
  (`answer_model`, vision-capable) — with a `grim` screenshot attached
  when Jev flags `needs_screen`, so "what's this error?" works. Set
  `screenshots = false` to keep images local.
- **Session memory**: turns persist to `session.jsonl` and the last N
  (`session_turns`, default 8) feed Jev + the answer model — "repeat
  that" and "yes, do it" follow-ups work across restarts.
- **Toolbelt**: launch/focus/close apps, workspace switch, notify,
  screenshot (`grim`), type text (`wtype`), guarded shell, file search —
  each with a risk tier (`safe` runs, `mutating` confirms, `shell`
  always confirms + denylist).
- **Autonomous agents**: "Wisp, agent — fix the tests in wisp"
  spawns a named `ori opencode run` task (all OpenRouter) you can
  check on or cancel later.
- **Omarchy shell plugin** (`io.github.duketopceo.wisp`): center bar icon,
  breathing-dark listening overlay, choice buttons, transcript/answer
  panel, agent status — all rendered from the daemon's `state.json`.
- **Week-by-week learning**: every clarify pick is logged; `wispd learn`
  stages a weekly proposal of criteria improvements you approve into
  `criteria_overrides.json`. Human-gated, never auto-applied.
- **Generic install**: works on a fresh Omarchy box — app catalog comes
  from `.desktop` files + `$PATH`. Optional adapters (dayflow activity
  mining, omaseal) layer on top when present; nothing personal is
  required or committed.
- **Text-first, optional voice**: answers render as widgets; set
  `voice.enabled = true` for `espeak`/`espeak-ng` spoken replies.

## Architecture

```
[Super+D] ──bind──▶ wisp-trigger ──ipc──▶ wispd (systemd user service)
                                                    │
        ┌───────────────────────────────────────────┤
        ▼                                           ▼
  pw-record 5s wav → whisper.cpp (ggml-small.en)   state.json ◀── poll
        │                                           (widgets)
        ▼
  Jev decisions (typesafe/jev-1.13)
  route: launch | tool | agent | answer | clarify
        │
   ┌────┼─────────┬───────────┐
   ▼    ▼         ▼           ▼
 launch toolbelt  agent    answer
        │      ori opencode  │
        ▼      run (named    ▼
  hyprctl /    persistent)  text widget
  grim / wtype  tasks.jsonl  (+ espeak)
```

## Install

```sh
git clone https://github.com/duketopceo/wisp
cd wisp
python3 wispd install     # files + shell plugin + systemd unit + Super+D bind
systemctl --user enable --now wispd
```

Prereqs: `pw-record` (or `arecord`), whisper.cpp at
`~/src/whisper.cpp` with `models/ggml-small.en.bin`, `hyprctl`,
`notify-send`. Optional: `grim`, `wtype`, `espeak-ng`, `ori`
(for agent spawning).

Secrets: `~/.config/wisp/.env` with `OPENROUTER_API_KEY=...` — or
`omaseal`-managed env. Never committed.

Config: `~/.config/wisp/config.toml` — hotkey, audio seconds,
whisper model, Jev model pin, risk/confidence thresholds, `voice.enabled`,
app→command map.

## Commands

| Command | What it does |
|---|---|
| `wispd daemon` | run the IPC daemon (systemd ExecStart) |
| `wispd trigger` | push-to-talk client (what the bind runs) |
| `wispd status` | dump daemon state.json |
| `wispd stop` | stop the daemon |
| `wispd choice <pick>` | answer a pending clarify prompt |
| `wispd learn` | stage this week's criteria proposal |
| `wispd harness` | rebuild `harness.json` from dayflow (optional) |
| `wispd install` | install files, plugin, unit, bind |

## Data files (local, never committed)

- `~/.local/share/wisp/session.jsonl` — persistent conversation turns
- `~/.local/share/wisp/decisions.jsonl` — every decision + result
- `~/.local/share/wisp/corrections.jsonl` — your clarify picks
- `~/.local/share/wisp/tasks.jsonl` + `tasks/<id>.log` — agent registry
- `~/.local/share/wisp/proposals/YYYY-WW.md` — weekly learning proposals
- `~/.config/wisp/harness.json` — mined app catalog (dayflow adapter)
- `~/.config/wisp/criteria_overrides.json` — approved learning edits
- `$XDG_RUNTIME_DIR/wisp/state.json` — live widget state
- `$XDG_RUNTIME_DIR/wisp/wispd.sock` — IPC socket

## Development

```sh
python3 -m unittest discover -s tests -v   # 65 headless tests
python3 -m py_compile wispd wisp/*.py wisp/tools/*.py
```

Layout: `wispd` (entry + install), `wisp/` (config, ipc, state, pipeline,
jev routing, learn, agents, tools/), `shell-plugin/` (quickshell plugin
for the Omarchy bar), `scripts/` (harness + criteria helpers),
`docs/` (brainstorm + plan for the assistant architecture).

## Safety

- Mutating tools (`close`, `type_text`, `task_cancel`) and all `shell`
  calls require confirmation — nothing fires silently.
- Shell commands pass a denylist before the confirmation prompt.
- Risk scores above `risk_threshold` block before any route executes.
- Learning proposals are staged files you approve; Jev criteria never
  mutate themselves.
