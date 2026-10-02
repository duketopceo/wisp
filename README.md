# Wisp

A resident voice companion for Omarchy (Hyprland). Press `Super+D`,
speak, and Wisp hears, decides, and acts: answer with the screen as
context, drive the desktop step by step, point at the thing it means,
or spawn a background coding agent — while holding the conversation
open across utterances.

Push-to-talk → PipeWire mic capture → whisper.cpp → Jev routing
(OpenRouter) → Talk answers with `[POINT]` ghost cursor / a guarded
act loop / named agent runtimes → companion orb, cursor bubble, and
listening pill on your desktop.

## Platforms

**Linux (Omarchy/Hyprland) is the primary platform** — the packaged
surface, the shell plugin, and the v1.0 verification target. **macOS is
supported**: `wispd-rs` runs the same pipeline through the platform
layer, with a launchd agent and an `/Applications` app catalog (see
`docs/MACOS.md`). Windows is scaffolded, not supported. CI runs the
suite on `ubuntu-latest` and `macos-latest`.

## Features

- **Resident daemon**: `wispd` runs as a systemd user service holding
  session, choice, and agent state on a unix socket. `Super+D` sends
  `listen`; the daemon owns the whole pipeline.
- **Two modes, Clicky-style**: Talk (hotkey → screen + voice → spoken
  answer + `[POINT]` ghost cursor) vs Agent (`"wisp agent …"` or the
  act route → a bounded tool-call loop that re-screenshots before every
  pointer action — no blind clicks).
- **Screen at trigger**: the screenshot is captured the moment you
  invoke Wisp and rides into the model — it sees the focused app, so
  it never asks "which app?". Set `screenshots = false` to keep images
  local.
- **Jev routing**: each utterance is classified as `launch`, `tool`,
  `agent`, `act`, `dictate`, `answer`, or `clarify` — Jev decides *what*
  to do, not whether; `clarify` only survives for a bare launch. The
  confidence gate keys on the *target* (app/tool).
- **Goal memory**: utterances sharing the focused app or the running
  goal's topic join one goal (`[agent] goal_ttl_s`, 10 min default) —
  "check robinhood" → "open it" → "type the URL" → "click GDX" is one
  task, not four. `ASK_USER:` answers come back through the voice
  backchannel without killing the goal.
- **Confirm-once**: one "yes" approves a `(tool, app)` pair for the
  session — follow-on steps in the same app don't re-prompt. Denylist
  and `allow_shell` unchanged.
- **Streaming answers**: OpenAI-compatible brains stream token deltas
  into `state.json`, so the answer types out live at your cursor.
- **Toolbelt**: launch/focus/close apps, workspace switch (natural
  language: "workspace 4"), notify, screenshot (`grim`), pointer
  (`click`/`move` with ghost-cursor guide), type text (`wtype`), guarded
  shell, file search, `mcp_call` — each with a risk tier (`safe` runs,
  `mutating` confirms, `shell` always confirms + denylist).
- **MCP access**: `mcp_call` speaks streamable-HTTP and stdio JSON-RPC —
  the inventory discovers configured servers (BrowserOS, Cloudflare,
  omaseal, dayflow, …) and `wispd connect <svc>` rides the local
  BrowserOS Strata gateway for OAuth (GitHub, Gmail, Slack, Notion,
  Linear, ~45 services). `browser` prefers the signed-in BrowserOS
  when its MCP server is live (`[agent] browseros_first`).
- **Local inventory passthrough**: `wispd inventory` maps installed
  apps, CLI tools, Omarchy plugins/binds, MCP servers, skills, and
  dayflow projects/goals into the act/answer context — the agent knows
  the terrain before it acts.
- **Autonomous agents**: "Wisp, agent — fix the tests in wisp" spawns a
  named task on your configured runtime (`opencode`/`codex`/`claude`/
  `devin`, `agent_runtime = "auto"` probes PATH) you can check on or
  cancel later.
- **Omarchy shell plugin** (`io.github.duketopceo.wisp`): companion orb
  with mode badge and goal line, cursor-adjacent answer bubble,
  bottom-center listening pill, panel with Now/Agents/Activity/Tele/
  Skills/Context/Connect tabs — all rendered from `state.json`.
- **Learning that ships as skills**: every run is labeled
  (`wispd label correct|incorrect` or panel ✓/✗); trajectories feed
  future attempts, and a verified multi-step workflow graduates into a
  `recipe-*` skill proposal — `wispd recipes approve` installs it.
  Human-gated, never auto-applied.
- **Interruptible**: `wispd interrupt` (or the ■ stop chip) cancels the
  in-flight turn without killing the daemon.
- **Generic install**: works on a fresh Omarchy box — app catalog comes
  from `.desktop` files + `$PATH`. Optional adapters (dayflow activity
  mining, omaseal) layer on top when present; nothing personal is
  required or committed.
- **Text-first, optional voice**: answers render as widgets; set
  `voice.enabled = true` for `espeak`/`espeak-ng` spoken replies.
  `password_manager = "1password"` lets the agent click through
  quick-unlock/passkey prompts — it never types your master password.

## Architecture

```
[Super+D] ──bind──▶ wisp-trigger ──ipc──▶ wispd (systemd user service)
                                                    │
        ┌───────────────────────────────────────────┤
        ▼                                           ▼
  pw-record 5s wav → whisper.cpp (ggml-small.en)   state.json ◀── poll
        │                                           (widgets)
        ▼
  Jev decisions (typesafe/jev-latest)
  route: launch | tool | agent | act | dictate | answer | clarify
        │
   ┌────┼─────────┬──────────────┐
   ▼    ▼         ▼              ▼
 launch toolbelt  act loop    answer (streamed)
        │      (re-observe,   │ + [POINT] ghost
        ▼      confirm-once)  │ cursor at pointer
  hyprctl /      │            ▼
  grim / wtype   ▼        cursor bubble /
        │      agents:    pill (+ espeak)
        ▼      opencode /
  mcp_call ──▶ codex / claude / devin
  (MCP servers, OAuth via Strata)
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
| `wispd interrupt` | cancel the in-flight turn, keep the daemon |
| `wispd choice <pick>` | answer a pending clarify prompt |
| `wispd label correct\|incorrect` | label the last run (soak metric) |
| `wispd context` | focused app + workspace map + inventory counts |
| `wispd inventory` | rescan local terrain (apps/CLIs/MCP/dayflow) |
| `wispd connect <svc>` | OAuth a connector via the Strata gateway |
| `wispd connect --list` | connector catalog + connected status |
| `wispd tele` / `wispd fails` | decision telemetry / recent failures |
| `wispd recipes` | draft skill proposals from trajectories |
| `wispd recipes approve <n>` | install a recipe as a skill |
| `wispd learn` | stage this week's criteria proposal |
| `wispd train stats\|history\|bank\|rebuild` | training arena — per-surface stats, run feed, skill bank |
| `wispd tasks` | background agents — status + live log tail |
| `wispd harness` | rebuild `harness.json` from dayflow (optional) |
| `wispd install` | install files, plugin, unit, bind |

## Data files (local, never committed)

- `~/.local/share/wisp/session.jsonl` — persistent conversation turns
- `~/.local/share/wisp/decisions.jsonl` — every decision + result
- `~/.local/share/wisp/labels.jsonl` — your correct/incorrect run labels
- `~/.local/share/wisp/trajectories.jsonl` — episodic act-loop memory
- `~/.local/share/wisp/inventory.json` — scanned local terrain map
- `~/.local/share/wisp/corrections.jsonl` — your clarify picks
- `~/.local/share/wisp/shadow.jsonl` — a second decider's answers per turn, when `[jev] shadow` is set
- `~/.local/share/wisp/tasks.jsonl` + `tasks/<id>.log` — agent registry
- `~/.local/share/wisp/proposals/` — recipe-* skill proposals + weekly
  criteria proposals
- `~/.local/share/wisp/clicklab.jsonl` — judged arena runs (clicklab)
- `~/.local/share/wisp/skillbank.json` — graduated/candidate/demoted
  task patterns per surface+app
- `~/.config/wisp/mcp.json` — OAuth-connected MCP services
- `~/.config/wisp/harness.json` — mined app catalog (dayflow adapter)
- `~/.config/wisp/criteria_overrides.json` — approved learning edits
- `$XDG_RUNTIME_DIR/wisp/state.json` — live widget state
- `$XDG_RUNTIME_DIR/wisp/wispd.sock` — IPC socket

## Development

```sh
python3 -m unittest discover -s tests -v   # 300+ tests, host-independent
python3 -m py_compile wispd wisp/*.py wisp/tools/*.py
```

Layout: `wispd` (entry + install), `wisp/` (config, ipc, state, pipeline,
jev routing, learn, agents, tools/), `shell-plugin/` (quickshell plugin
for the Omarchy bar), `scripts/` (harness + criteria helpers),
`docs/` (brainstorm + plan for the assistant architecture).

## Safety

- Mutating tools (`click`, `type_text`, `close`, `task_cancel`, …) and
  all `shell`/`key` calls require confirmation — nothing fires silently.
  Confirm-once caches a yes per `(tool, focused app)` for the session.
- Shell commands pass a denylist before the confirmation prompt.
- Risk scores above `risk_threshold` block before any route executes.
- Learning proposals and recipe skills are staged files you approve;
  nothing installs itself.
- The agent may click through a password-manager prompt but is
  instructed never to type a master password (`password_manager`).
