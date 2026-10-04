---
plan: dim-companion-crossplatform
created: 2026-09-26
origin: docs/brainstorms/2026-09-26-dim-companion-cross-platform-requirements.md
status: "superseded by 2026-10-04-0100-feat-wisp-unified-plan.md"
---

# Wisp — Cross-Platform Companion (Hey Clicky clone, BYO-brain)

## Problem frame

Wisp is a working Omarchy voice assistant (Python `wispd` daemon, Jev
routing, toolbelt, act loop, quickshell plugin, 83 tests). Target: a
cross-platform, open-source desktop companion — the Hey Clicky interaction
model — where the user powers it however they want (OpenRouter default,
Jev optional router, Ollama/LM Studio/MLX/OpenAI-compatible endpoints,
CLI agent runtimes for agent mode). First shell: the live Omarchy
quickshell plugin. Then macOS + Windows + generic Linux shells.

## Key decisions (settled)

- **Rust core via parity port** (`rs/wispd/` crate). Python `dim/` stays
  the reference implementation until the Rust daemon reaches contract
  parity; the IPC + `state.json` contract is the boundary, so the
  plugin never cares which serves it. Rationale: consumer packaging
  requires a single codesigned binary; porting is cheapest now, before
  Clicky features (cursor pointing, walkthroughs, TTS) exist.
- **Linux adapters shell out** to `grim`/`wtype`/`pw-record`/`hyprctl` —
  research shows enigo (Chromium/Electron text-injection bug #336,
  experimental libei) and xcap (slow portal fallback) are weaker on
  Wayland than the current approach. Crates serve macOS/Windows where
  they're mature: `enigo`, `xcap`, `global-hotkey` (XDG portal covers
  Hyprland 0.20+/GNOME 48+/KDE 5.27+), `cpal`, `tray-icon`.
- **Brain layer is a trait**, not a fork per provider. One internal
  interface (text gen, vision flag, optional tool-calls); providers are
  runtime config. OpenRouter is the zero-config default; Jev is an
  optional router (`router = jev | chat | off`); CLI runtimes
  (`ori opencode`, `codex`, `claude`, `devin`) plug agent mode only —
  spawned, never API'd.
- **Cursor pointing via `[POINT:x,y:label]` tags** parsed from model
  output → layer-shell fullscreen transparent overlay draws the pointer.
  Logical-vs-physical coords handled via compositor scale (eDP-1 is
  scale 2 on omarchy-max). Cursor *pointing* ships; cursor *clicking*
  is deferred — the pointer is guidance, not control.
- **Python is not deleted at parity** — it stays as the reference/test
  oracle until the Rust core has lived a full release cycle.

## Dependency-ordered units

### Wave 1 — Contract + parity scaffold

**U1: IPC/state contract spec + golden fixtures**
- Freeze `dim/ipc.py` command surface and `state.json` schema into
  `docs/IPC_CONTRACT.md` with JSON fixtures per command/transition.
- Golden test: Python daemon output parsed by a contract checker that
  the Rust impl will also run.
- Test: `tests/test_contract.py` — every fixture validates against the
  live Python daemon's actual output.

**U2: `rs/` workspace + Linux parity core**
- New `wispd-rs` binary: tokio unix-socket server (same path), same
  commands (`listen`, `status`, `choice`, `stop`, `task_status`,
  `task_cancel`), same atomic `state.json` writes, same
  `config.toml`/`.env` layout (toml crate), same `decisions.jsonl` /
  `session.jsonl` formats (serde_json).
- Linux adapters as trait impls shelling out: `pw-record`, `whisper-cli`,
  `grim`, `wtype`, `hyprctl`, `notify-send`, `espeak-ng`.
- Jev client: `reqwest` POST to `/api/alpha/decisions`; OpenRouter chat
  client with `image_url` support.
- Port the toolbelt verbatim: same registry, same risk tiers, same
  denylist, same confirm semantics; `tool_schemas()` emitted identically.
- Port `act` loop: same bounds (8 steps / 2 consecutive errors).
- Test: `rs/tests/` parity suite driven by U1 fixtures; run existing
  Python suite unchanged against Python (regression oracle).
- Gate: `wispd-rs` serves `listen→done` on omarchy-max against real
  whisper/Jev/OpenRouter, plugin unchanged.

### Wave 2 — Clicky UX on the proven shell

**U3: Cursor pointing overlay**
- Parse `[POINT:x,y:label]` (and `[POINTS]` lists for walkthroughs) from
  answer/agent text; publish `points` in `state.json`.
- New `Pointer.qml` overlay surface (layer-shell overlay layer,
  click-through): animated cursor that flies to (x,y), label chip,
  numbered steps for multi-point walkthroughs, auto-hide timer.
- Coordinate normalization: screenshot pixels → logical coords via
  `hyprctl monitors -j` scale; unit-test the mapping with scale=2 and
  scale=1 fixtures.
- Prompt change: answer system prompt documents the tag grammar when
  `needs_screen` fired.

**U4: Spoken answers (TTS)**
- `speak()` already exists behind config; make the answer route call it
  by default when `voice_out=true`; espeak-ng on Linux now, `say` on
  macOS and SAPI on Windows land with their adapters.
- Barge-in: a new `listen` during TTS kills the speech process.

**U5: Dictation + richer orb states**
- `route=dictation` → transcript straight to `type_text` (existing
  tool; mutating → confirm gate applies).
- Companion.qml: add `speaking` state, waveform from `level`, point
  indicator badge when `state.json.points` non-empty.

### Wave 2.5 — Memory + self-authored skills (Hermes pattern)

**U5b: Curated memory layer**
- `MEMORY.md` + `USER.md` in the data dir — bounded (~800/500 tok),
  frozen-snapshot injection into every brain call's system context.
- `memory` tool in the registry: `add | replace | remove`,
  substring-matched (Hermes `memory_tool.py` semantics verbatim).
- Python impl first (it ships in the live daemon today), then ported
  with U2 parity work — the contract is file-level, so both cores can
  share the same files.
- Test: `tests/test_memory.py` — add/replace/remove round-trips, bound
  enforcement, frozen-snapshot injection into `ask_chat` calls.

**U5c: sqlite-vec recall store**
- `~/.local/share/wisp/recall.db`: turns + corrections + distilled
  notes embedded via a configurable embedding model (OpenRouter
  embeddings default; `none` = lexical FTS5 fallback so recall works
  fully offline without any key).
- `recall` tool: `search <query>` → top-k injected context; automatic
  write-through on every turn + correction.
- Test: `tests/test_recall.py` — write-through, top-k ordering,
  lexical fallback when no embedding provider configured.

**U5d: Self-authored skills**
- `~/.local/share/wisp/skills/*/SKILL.md` + `skill_manage` tool
  (create/edit/patch/delete/write_file/remove_file — Hermes semantics)
  + `skill_view` for progressive disclosure (index in system context,
  bodies loaded on demand).
- `learn` route/command: "Wisp, learn X" → agent gathers material with
  existing tools and authors a conforming SKILL.md; re-running on the
  same topic folds into the existing skill.
- Skills may declare toolbelt additions (name/description/script) that
  register at daemon start — procedural memory becomes capability.
- Mutating tier: skill writes hit the filesystem under the data dir —
  safe tier for writes inside `skills/`, confirm for deletes.
- Test: `tests/test_skills.py` — create/view/edit lifecycle, index
  injection, toolbelt registration, learn-command fold-in.

### Wave 3 — Pluggable brains

**U6: Brain provider trait + registry (Rust)**
- `trait Brain { chat(messages, opts) -> reply; supports_vision();
  supports_tools(); }` — providers: `openrouter`, `openai_compat`
  (base_url+model; covers Ollama, LM Studio, vLLM, corporate gateways),
  `mlx` (mlx-lm server's OpenAI-compat endpoint + direct probe),
  `ollama` (native `/api/chat` — richer than the compat shim).
- Config: `[brain] default = "openrouter:meta-llama/llama-4-maverick"`,
  `router = "jev" | "chat" | "off"`, `agent_runtime = "opencode" |
  "codex" | "claude" | "devin"`. `chat` router = transcript+screenshot
  straight to the answer model; `off` = always clarify→choice.
- PATH probe for agent runtimes; missing runtime → error state, not
  silent fallback.
- Tests: provider parsing, vision/tool gating, Jev-off path, runtime
  probe with stub PATH entries.

### Wave 4 — macOS + Windows adapters and shells

**U7: macOS adapter + tray shell**
- Adapters: `enigo` (input), `xcap` (ScreenCaptureKit path), `cpal`
  (mic), `say` (TTS), `global-hotkey`, `tray-icon` menu-bar item;
  window ops via AppleScript/AX where needed.
- Shell: minimal Tauri tray app? No — settled decision is thin native:
  `tray-icon` + a NSPanel-equivalent via `objc2` is heavy; cheaper:
  Tauri v2 single-crate shell reusing the webview orb. Decide at
  implementation spike; both consume the socket contract.
- Codesigning/notarization captured as release checklist, not code.

**U8: Windows adapter + tray shell**
- `enigo`/`xcap` (WindowsGraphicsCapture)/`cpal`/SAPI/`global-hotkey`/
  `tray-icon`; named-pipe transport (`tokio::net::windows::named_pipe`)
  behind the same contract; Tauri or WinUI3 shell — same spike decision.

**U9: Generic-Linux (non-Hyprland) adapter**
- GNOME/KDE: hotkey via XDG GlobalShortcuts portal (`global-hotkey`
  wayland path — confirmed supported GNOME 48+, KDE 5.27+), screenshot
  via portal/`gnome-screenshot`, input via `ydotool` (portal-safe) or
  wtype fallback; AppIndicator tray.

### Wave 5 — Ship

**U10: Packaging + release**
- `cargo-dist` or `cargo-packager`: `.pkg` (mac, signed+notarized),
  `.msi`/winget (win), `.deb`/AUR + AppImage (linux).
- `wispd install` per-OS service registration (launchd/systemd/Task
  Scheduler).
- Docs: install, config reference, brain provider table, security model.
- Version `1.0.0` tag; Python reference moves to `legacy/` or stays
  `dim/` clearly marked.

## Risks / unknowns deferred to implementation spikes

- Whether Wayland layer-shell pointer overlay can be click-through AND
  receive enough events for dismiss — prototype in U3 first hour.
- xcap Wayland fallback latency — Linux keeps `grim`, so risk is
  macOS/Windows-only.
- Tauri vs native for mac/win shells — both satisfy the contract; pick
  by smallest total code at spike time.
- Jev over `reqwest` — trivial, but decision schema validation must
  reject unknown question types identically to Python (fixture-driven).

## Traceability

- Requirements 1–7 ← U1 (contract), U2 (parity core incl. gates/errors),
  U3 (points), U4 (TTS), U5b–U5d (memory + skills), U6 (brains),
  U7–U10 (multi-OS + packaging). Omarchy Linux is the primary/first
  target — all Wayland decisions verified against Hyprland first.
- Non-goals enforced: no proxy/hosted service anywhere; no wake word;
  no pixel clicking (only `[POINT]` guidance).
- Forbidden: GPT-6 Astra never appears as a runtime or dev default.
