# dim-agent — Repo Index

**What:** Hey Clicky-style desktop AI companion. Push-to-talk voice →
routing → guarded actions. Python reference daemon + Rust parity core
(`dimd-rs`). OpenRouter-powered, Jev optional, BYO-provider planned.

## Entry points

| Path | What |
|---|---|
| `dimd` | Python CLI/daemon: `daemon`, `trigger`, `status`, `stop`, `choice`, `config [set k v]`, `learn`, `harness`, `install` |
| `rs/dimd/` | Rust parity core (`dimd` binary) — same socket + state contract |
| `shell-plugin/` | Omarchy quickshell plugin (bar widget + companion orb overlay) |
| `shells/debug/shell.qml` | Management/debug app (`qs -c dim-debug`, launcher entry "Dim") |

## Core modules (`dim/`)

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
| `trace.py` | dev trace — `trace.jsonl` event stream (turn id, stage, kind, ms, data); `dimd trace` CLI |
| `learn.py` | corrections → weekly human-gated criteria proposals |
| `agents.py` | `ori opencode` background task registry (spawn/status/cancel, `tasks.jsonl`) |
| `tools/` | toolbelt: `__init__.py` registry + tiers + `tool_schemas()`; `desktop.py`/`system.py`/`adapters.py` shell-outs |
| `util.py` | shared slug/text helpers used by agents + skills |

## Rust modules (`rs/dimd/src/`)

Mirror of `dim/`: `main.rs` (IPC dispatch), `ipc.rs`, `state.rs`,
`config.rs`, `brain.rs` (Jev + chat clients), `pipeline.rs`,
`tools.rs`, `agents.rs`, `session.rs`, `learn.rs`, `harness.rs`,
`memory.rs`, `recall.rs` (rusqlite FTS5), `skills.rs`, `util.rs`
(shared helpers incl. `run_timeout`). `tests/parity.rs` replays
`tests/fixtures/ipc_commands.jsonl` against a live spawned daemon.

## Contracts & docs

| Path | What |
|---|---|
| `docs/IPC_CONTRACT.md` | **frozen** socket + `state.json` + data-file contract — both cores implement it |
| `docs/plans/` | implementation plans (latest: cross-platform companion); `docs/plans/units/` holds per-unit plans linked from GitHub issues |
| `docs/HANDOFF.md` | verification checklist + residuals |
| `tests/` | Python unittest suite (run: `python -m unittest discover -s tests`); `rs/dimd` has `cargo test` + `tests/parity.rs` |

## Runtime layout (not in repo)

`~/.config/dim-agent/` config.toml + .env + harness.json ·
`~/.local/share/dim-agent/` session/decisions/corrections/tasks.jsonl,
recall.db, MEMORY.md, USER.md, skills/, proposals/ ·
`$XDG_RUNTIME_DIR/dim-agent/` state.json + dimd.sock ·
daemon: `systemctl --user dimd` (runs `~/.local/opt/dim-agent/dimd`);
`~/.local/bin/dimd` symlinks there.
