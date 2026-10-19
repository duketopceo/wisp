# wisp — Repo Index

**What:** Hey Clicky-style desktop AI companion. Hold push-to-talk → local
STT → Jev routing → guarded actions. Python reference daemon (`wispd` script
+ `wisp/`) and Rust parity core (`rs/wispd/`). Pluggable `[brain.*]`
providers (OpenRouter default; local Ollama/LM Studio/MLX supported).

## Entry points

| Path | What |
|---|---|
| `wispd` | Python CLI + daemon installer/IPC host; commands live in `wisp/cli/` |
| `rs/wispd/` | Rust parity core (`wispd` binary) — same socket + state contract |
| `shell-plugin/` | Omarchy quickshell plugin: `BarWidget.qml` (mark + live pill), `Panel.qml`, `Companion.qml` overlay |
| `shells/debug/shell.qml` | Management/debug app (`qs -c dim-debug`, launcher entry "Wisp") |

Common CLI groups (full tree: `wispd --help`): `daemon`, `status`, `stop`,
`interrupt`, `trigger`, `watch`, `choice`, `doctor`, `health`, `latency`,
`spend`, `binds`, `onboard`, `cua`, `task`, `memory`, `suggest`, `label`,
`context`, `train`, `review`, `learn`, `skills`, `recipes`, `trace`,
`eval`, `config`, `theme`, `batch`, `connect`, `sync`, `inventory`, `tui`,
`completion`.

## Core modules (`wisp/`)

| File | Role |
|---|---|
| `pipeline.py` | Orchestrator: `run_listen`, cancel/error paths; re-exports stage APIs |
| `stage_capture.py` | Mic, transcribe, screenshot/window context |
| `stage_route.py` | Jev / heuristic router, rescues, clarify prompts |
| `stage_execute.py` | Tools, act loop, agents, dictation |
| `stage_speak.py` | Stream + speak answers, close turn |
| `stage_ctx.py` | Per-turn context bag passed between stages |
| `act.py` | Bounded tool-call loop (defaults: ≤8 steps via `[agents] act_max_steps`, ≤2 consecutive errors) |
| `dictate.py` | LLM-aware dictation (U6) — raw/cleanup/compose modes, `[dictation.profiles.*]` per-app style, terminal newline guard, `dictation.json` corrections, wordink→type→paste insert |
| `voicepick.py` | Map spoken utterances to pending choice/confirm options or stop words |
| `config.py` | config.toml flat parser/writer, paths, API key, harness load |
| `ipc.py` | unix-socket server + client (newline-delimited JSON) |
| `state.py` | atomic `state.json` writer / StateBus |
| `session.py` | `session.jsonl` append + tail for follow-up context |
| `memory.py` | `MEMORY.md`/`USER.md` curated memory — `memory` tool; frozen snapshot injection |
| `recall.py` | `recall.db` — sqlite FTS5 (+ optional sqlite-vec embeddings) for `recall` tool |
| `skills.py` | `skills/*/SKILL.md` — `skill_manage`/`skill_view`, `skill_<name>` toolbelt |
| `speech.py` | TTS with barge-in — kills on new `listen` / `stop` |
| `trace.py` | dev trace — `trace.jsonl`; `wispd trace show|digest` |
| `learn.py` | corrections → weekly human-gated criteria proposals |
| `brain.py` | pluggable answer providers — `[brain] default = "name:model"` tables |
| `agents.py` | background task registry; `[brain] agent_runtime` |
| `goals.py` | cross-utterance goal continuity — `goal_ttl_s` |
| `trajectories.py` | episodic act memory — `similar()`, `propose_recipes()` |
| `context.py` | prompt context — app, windows, inventory, act context modes |
| `inventory.py` | local-terrain scanner → `inventory.json` |
| `mcpauth.py` | OAuth via BrowserOS Strata — `wispd connect` |
| `telemetry.py` | decision telemetry + trace digest helpers |
| `action_stats.py` | per-app tool outcome stats for act prompting |
| `judge.py` | Jev-as-judge verdicts for act runs |
| `train.py` | training arena — `skillbank.json`, label-grounded legend distillation |
| `points.py` | `[POINT:x,y:label]` → ghost-cursor points |
| `sense.py` | opt-in activity collector → `activity.jsonl` |
| `suggest.py` | Jev-gated suggestion miner → approval cards |
| `evalroute.py` | Jev vs heuristic route experiments |
| `theme.py` | GUI theme/table helpers |
| `tui.py` | `wispd tui` terminal surface |
| `vocab.py` | Whisper prompt vocab from MEMORY + inventory |
| `platform.py` | OS/desktop adapter seam |
| `cua.py`, `cua_safety.py`, `grounding.py`, `pointer.py` | computer-use stack |
| `cancel.py` | turn cancel + `PromptBroker` for choices |
| `health.py`, `ledger.py`, `batch.py`, `hypr.py`, `onboard.py`, … | ops, spend, binds, setup |
| `tools/` | toolbelt registry + `desktop.py`/`system.py`/`social.py`/… |
| `cli/` | argparse registry (`registry.py`) and command modules |

## Rust modules (`rs/wispd/src/`)

Mirror of `wisp/`: `main.rs` (IPC dispatch), `ipc.rs`, `state.rs`,
`config.rs`, `brain.rs`, `pipeline.rs`, `tools.rs`, `agents.rs`,
`session.rs`, `learn.rs`, `harness.rs`, `memory.rs`, `recall.rs`,
`skills.rs`, `util.rs`. `tests/parity.rs` replays
`tests/fixtures/ipc_commands.jsonl` against a live spawned daemon.

## Contracts & docs

| Path | What |
|---|---|
| `docs/IPC_CONTRACT.md` | Socket + `state.json` + data-file contract v1 — both cores implement it; additive fields allowed |
| `docs/INSTALL.md` | install guide: release bundles, `wispd install`, secrets, per-OS notes |
| `docs/CONFIG.md` | config.toml reference + CLI surface |
| `docs/CUA.md` | computer-use safety, grounding, troubleshooting |
| `docs/HANDOFF.md` | current verification checklist + open residuals |
| `docs/archive/` | historical notes (e.g. Sep 2025 machine migration) |
| `docs/plans/` | implementation plans; `docs/plans/units/` per-unit plans |
| `tests/` | `python -m unittest discover -s tests`; `cargo test` in `rs/wispd` |

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
| `wisp/platform.py` | OS adapter seam — per-OS command tables, runtime dirs |
| `rs/wispd/src/platform.rs` | Rust mirror |
| `docs/MACOS.md` | macOS paths, permissions, hotkey |
| `docs/WINDOWS.md` | Windows TCP transport, schtasks |
| `docs/LINUX.md` | Generic Linux desktop matrix |
| `tests/test_ipc_tcp.py` | TCP transport roundtrip |

## Plans

Plan of record: `docs/plans/2026-10-04-0100-feat-wisp-unified-plan.md`
(W1–W34; crosswalk in `ROADMAP.md`).
