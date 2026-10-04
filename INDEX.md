# wisp — Repo Index

**What:** Hey Clicky-style desktop AI companion. Push-to-talk voice →
routing → guarded actions. Python reference daemon + Rust parity core
(`wispd-rs`). OpenRouter-powered, Jev optional, BYO-provider planned.

## Entry points

| Path | What |
|---|---|
| `wispd` | Python CLI/daemon: `daemon`, `trigger`, `status`, `stop`, `choice`, `config [set k v]`, `learn`, `harness`, `install` |
| `rs/wispd/` | Rust parity core (`wispd` binary) — same socket + state contract |
| `shell-plugin/` | Omarchy quickshell plugin (bar widget + companion orb overlay) |
| `shells/debug/shell.qml` | Management/debug app (`qs -c dim-debug`, launcher entry "Wisp") |

## Core modules (`wisp/`)

| File | Role |
|---|---|
| `pipeline.py` | listen cycle: record → whisper → Jev route → execute; context assembly, timing, decisions log |
| `act.py` | bounded tool-call loop (≤8 steps, ≤2 consecutive errors) for `act`/`learn` routes |
| `config.py` | config.toml flat parser/writer, paths, API key, harness load |
| `ipc.py` | unix-socket server + client (newline-delimited JSON) |
| `state.py` | atomic `state.json` writer |
| `session.py` | `session.jsonl` append + tail for follow-up context |
| `memory.py` | `MEMORY.md`/`USER.md` curated memory — `memory` tool (add/replace/remove), frozen snapshot injection |
| `recall.py` | `recall.db` sqlite FTS5 store — `recall` tool, write-through on turns/corrections |
| `skills.py` | `skills/*/SKILL.md` self-authored skills — `skill_manage`/`skill_view` tools, `skill_<name>` toolbelt registration |
| `speech.py` | TTS replies with barge-in — tracks espeak/`[voice].cmd` child pid, killed on `listen`/`stop` |
| `trace.py` | dev trace — `trace.jsonl` event stream (turn id, stage, kind, ms, data); `wispd trace` CLI |
| `learn.py` | corrections → weekly human-gated criteria proposals |
| `brain.py` | pluggable answer providers — `[brain] default = "name:model"` + `[brain.<name>]` tables (kind openai_compat\|ollama, base_url, key_env, vision, tools); router `jev`\|`chat`\|`off` |
| `agents.py` | background task registry (spawn/status/cancel, `tasks.jsonl`); `[brain] agent_runtime` = opencode\|codex\|claude\|devin, PATH-probed |
| `goals.py` | cross-utterance goal continuity — join/record/close, `goal_ttl_s` TTL; `ASK_USER` keeps goals open |
| `trajectories.py` | episodic act-loop memory (`trajectories.jsonl`) — `similar()` retrieval, label join via decision transcript, `propose_recipes()` drafts human-gated `recipe-*` skills |
| `context.py` | prompt context assembly — focused app, `[windows]` workspace map, inventory `[env]` line, password_manager instruction |
| `inventory.py` | local-terrain scanner → `inventory.json`: apps, cli_tools, mcp servers, omarchy plugins/binds, dayflow, skills (24h TTL) |
| `mcpauth.py` | OAuth connector flow via the local BrowserOS Strata gateway — `wispd connect <svc>`, catalog list, mcp.json registration |
| `telemetry.py` | decision telemetry + `wispd tele` digest |
| `action_stats.py` | per-app tool outcome stats — planner bias block injected into the act system prompt |
| `judge.py` | Jev-as-judge — structured success/efficiency/waste verdict per act run |
| `train.py` | training arena — `skillbank.json` per-(surface,app,task) streaks, auto-graduation (≥3 streak, eff≥0.9), demotion, `hint_for()` proven-sequence injection |
| `points.py` | `[POINT:x,y:label]` tag parsing → normalized ghost-cursor points |
| `sense.py` | opt-in proactive collector — dayflow + hyprctl deltas → `activity.jsonl` |
| `suggest.py` | Jev-gated suggestion miner → orb "an idea" cards (approval-only) |
| `evalroute.py` | route-eval helper for Jev criteria experiments |
| `theme.py` | GUI theme/table helpers |
| `tui.py` | `wispd tui` terminal surface |
| `vocab.py` | Whisper prompt vocab — MEMORY.md facts + discovered CLI/app names prime STT |
| `platform.py` | OS/desktop adapter seam — active window, launch/focus/workspace cmd builders per platform |
| `tools/` | toolbelt: `__init__.py` registry + tiers + `tool_schemas()` + `mcp_call` client (HTTP/stdio JSON-RPC); `desktop.py`/`system.py`/`adapters.py` shell-outs |
| `util.py` | shared slug/text helpers used by agents + skills |

## Rust modules (`rs/wispd/src/`)

Mirror of `wisp/`: `main.rs` (IPC dispatch), `ipc.rs`, `state.rs`,
`config.rs`, `brain.rs` (Jev + pluggable provider clients), `pipeline.rs`,
`tools.rs`, `agents.rs`, `session.rs`, `learn.rs`, `harness.rs`,
`memory.rs`, `recall.rs` (rusqlite FTS5), `skills.rs`, `util.rs`
(shared helpers incl. `run_timeout`). `tests/parity.rs` replays
`tests/fixtures/ipc_commands.jsonl` against a live spawned daemon.

## Contracts & docs

| Path | What |
|---|---|
| `docs/IPC_CONTRACT.md` | **frozen** socket + `state.json` + data-file contract — both cores implement it |
| `docs/INSTALL.md` | install guide: release bundles, `wispd install` layout, secrets, per-OS notes |
| `docs/CONFIG.md` | config.toml reference — every key, grouped, with env overrides |
| `docs/plans/` | implementation plans (latest: cross-platform companion); `docs/plans/units/` holds per-unit plans linked from GitHub issues |
| `docs/HANDOFF.md` | verification checklist + residuals |
| `tests/` | Python unittest suite (run: `python -m unittest discover -s tests`); `rs/wispd` has `cargo test` + `tests/parity.rs` |

## Runtime layout (not in repo)

`~/.config/wisp/` config.toml + .env + harness.json ·
`~/.local/share/wisp/` session/decisions/corrections/tasks.jsonl,
recall.db, MEMORY.md, USER.md, skills/, proposals/ ·
`$XDG_RUNTIME_DIR/wisp/` state.json + wispd.sock ·
daemon: `systemctl --user wispd` (runs `~/.local/opt/wisp/wispd`);
`~/.local/bin/wispd` symlinks there.

## Platform adapters

| Path | What |
|---|---|
| `wisp/platform.py` | OS adapter seam — per-OS command tables (record/screenshot/type/TTS/notify/wm), runtime dirs, deps hints; `WISP_OS` override |
| `rs/wispd/src/platform.rs` | Rust mirror of the platform seam; `*_for(Os,…)` testable variants |
| `docs/MACOS.md` | macOS adapter: paths, command map, permission caveats, hotkey + shell decision |
| `docs/WINDOWS.md` | Windows adapter: TCP transport, command map, schtasks install, residuals |
| `tests/test_ipc_tcp.py` | TCP transport roundtrip (Windows path proven on Linux) |
| `docs/LINUX.md` | Generic-Linux adapter: desktop detection + per-desktop command matrix |
