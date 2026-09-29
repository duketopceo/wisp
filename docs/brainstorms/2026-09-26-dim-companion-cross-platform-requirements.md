# Wisp — Cross-Platform AI Companion (Hey Clicky clone) — Requirements

Date: 2026-09-26 · Status: settled for planning
Origin: user direction — "build for big: Linux, macOS, Windows; open source;
OpenRouter-powered with Jev; pluggable backends (Codex, Claude, Devin,
LM Studio, MLX, OpenAI-compatible endpoint, Ollama) — Hey Clicky, but
powered however the user wants."

## What we're building

Wisp becomes a **cross-platform, open-source AI desktop companion** — the
Hey Clicky interaction model (persistent orb, push-to-talk, screen-aware
spoken/visual guidance, background agents) — with a **provider-agnostic
brain layer** so the user powers it however they want: OpenRouter (default),
Ollama, LM Studio, MLX, any OpenAI-compatible endpoint, and CLI agent
runtimes (ori opencode, codex, claude, devin) for agent mode.

A thin **per-OS shell** renders the companion UI; a **single portable core**
owns the daemon, IPC contract, state, session memory, toolbelt, act loop,
routing, and learning loop. First shell: the existing Omarchy quickshell
plugin, already live.

## Product shape

- **Companion presence**: persistent floating orb (idle/listening/
  thinking/acting/error), click → expanded card (transcript, answer,
  choices, agent progress). Exists already as `Companion.qml`.
- **Talk mode**: hotkey → mic + screenshot → brain answers, with
  optional spoken reply (system TTS; pluggable TTS later).
- **Cursor pointing**: model responses may carry `[POINT:x,y:label]`
  tags → overlay draws a pointer at that pixel. The signature Clicky
  interaction; Wayland layer-shell fullscreen transparent surface.
- **Walkthroughs**: multi-step numbered guidance, each step may point.
- **Agent mode**: "agent" keyword or route → background agent task
  (ori opencode / codex / claude / devin — pluggable, user-configured).
- **Dictation**: transcript can be typed into the focused app via
  `type_text` (voxtype stays separate on `Alt+Space`; Wisp hotkey is
  `Super+D` — configurable per OS).
- **Session memory**: persistent turns, follow-ups across restarts.
- **Learning loop**: weekly human-gated corrections → routing criteria.

## Brain layer (the differentiator)

Pluggable backends behind one internal interface — text generation,
vision (screenshot), optional tool-calling:

| Backend | Role | Notes |
|---|---|---|
| OpenRouter chat | **default** answer/act model | `meta-llama/llama-4-maverick` today; user-configurable |
| Jev (OpenRouter decisions) | **optional** router | config `router = jev`; structured risk/route/confidence |
| OpenAI-compatible endpoint | generic | covers Ollama (`/v1`), LM Studio, llama.cpp, vLLM, corporate gateways |
| MLX | Apple Silicon local | via mlx-lm server (OpenAI-compatible) or direct |
| CLI agent runtimes | agent mode only | `ori opencode`, `codex`, `claude`, `devin` — spawned, not API'd |

Config shape (conceptual): `brain.default = openrouter:<model> |
openai-compat:<base_url>:<model> | ollama:<model> | mlx:<model>`;
`brain.router = jev | chat | off`; `brain.agent = opencode | codex |
claude | devin`. Secrets stay in the existing `.env` / keyring — never
in git, never in the binary (Hey Clicky's worker-proxy pattern is a
non-goal: users bring their own keys or run local).

## Architecture (settled: Option A — Rust core, parity port)

```
┌──────────────────────────────────────────────────┐
│ Shells (thin, per-OS UI)                         │
│  Omarchy quickshell plugin  ← FIRST, already live│
│  macOS menu-bar app · Windows tray ·             │
│  Linux GNOME/other (AppIndicator/webview)        │
├──────────────────────────────────────────────────┤
│ wispd — portable core daemon (Rust)               │
│  IPC (unix socket / named pipe) · state.json     │
│  session.jsonl · decisions.jsonl · corrections   │
│  brain layer (pluggable providers)               │
│  tool registry · act loop · risk gates           │
│  learning loop                                   │
├──────────────────────────────────────────────────┤
│ OS adapters (per-platform implementations)       │
│  audio capture · screenshot · text injection ·   │
│  window ops · global hotkey · TTS · tray         │
├──────────────────────────────────────────────────┤
│ Brains: OpenRouter · Jev · OpenAI-compat ·       │
│  Ollama · LM Studio · MLX · CLI agents           │
└──────────────────────────────────────────────────┘
```

**Sequencing rationale**: the existing Python `wispd` is the reference
implementation (83 tests). A new Rust crate (`rs/` or `core/`, same repo)
implements the **same socket + `state.json` contract** until parity, then
becomes default. The quickshell plugin never knows which core serves it.
Linux adapters keep shelling out to `grim`/`wtype`/`pw-record`/`hyprctl`
(research shows enigo/xcap are weaker than these on Wayland); crates
(`enigo`, `xcap`, `global-hotkey`, `cpal`, `tray-icon`) serve
macOS/Windows where they're mature.

## Requirements (must hold at v1)

1. Socket/JSON contract is the stable boundary — documented, versioned;
   shells are replaceable without core changes.
2. All mutating/shell actions gated: denylist, `allow_shell`, risk tiers,
   user confirmation path — enforced in core, not shells.
3. Every failure path surfaces to `state.json` visibly (error orb state).
4. Brain backends are runtime-configurable, no recompile; OpenRouter is
   the zero-config default after key entry.
5. One hotkey press starts listening immediately (acknowledged state
   before STT completes); per-stage timings recorded.
6. Screenshot capture is opt-in per request (needs_screen), never stored
   beyond the request.
7. Open source, MIT or Apache-2.0; installable via package manager or
   single binary per OS.

## Memory & self-authored skills (Hermes pattern)

Day-to-day context survives restarts **without** a heavy service
(Kurultai is too resource-hungry to be the default; it stays an optional
external provider for users who want it):

- **Bounded curated memory** — `MEMORY.md` (~800 tok: environment,
  learned facts) + `USER.md` (~500 tok: preferences, style) in the data
  dir, injected as a frozen block in every brain call's system context.
  The agent curates it via a `memory` tool (add/replace/remove,
  substring-matched). Frozen-snapshot pattern preserves prompt caching.
- **Long-term recall** — `sqlite-vec` embedded store: turns, corrections,
  and distilled notes vector-indexed in one `.db` file; retrieved into
  context on demand. Zero servers. LanceDB is the escape hatch if the
  corpus outgrows brute-force KNN.
- **Self-authored skills** — `skills/*/SKILL.md` in the data dir +
  a `skill_manage` tool (create/edit/patch/delete/write_file) +
  `skill_view` for progressive disclosure. Successful approaches become
  reusable skills; a `learn` route/command lets the user point Wisp at
  material ("learn how Omarchy plugin packaging works") and the agent
  authors the skill. Skills may register new toolbelt entries.
- Session turns (`session.jsonl`) stay the short-term layer; memory is
  the curated layer on top.

## Explicit non-goals (for now)

- No cloud proxy / hosted service — users bring keys or run local models.
- No wake word ("Hey Wisp") — push-to-talk only for v1.
- No telemetry/analytics.
- Pixel-level computer-use clicking beyond `type_text`/hotkeys —
  cursor *pointing* yes, cursor *clicking* deferred (biggest risk surface).
- Rowboat integration.
- Kurultai as the default memory backend — optional provider only.
- Cloud-synced memory — everything stays on-device in v1.

## Open questions for planning

- Repo layout: monorepo `dim/` (py reference) + `rs/` (core) + `shells/`?
- Crate IPC transport on Windows (named pipes vs TCP localhost).
- TTS strategy: espeak/piper on Linux; system TTS on macOS/Windows.
- Whether agent runtimes are detected at runtime (PATH probe) vs config.

## Success criteria

- `Super+D` on Omarchy → orb breathes → transcript → screen-aware spoken
  or text answer → optional cursor point → done, in <5s typical.
- Same binary features on macOS/Windows shells when they land.
- Swapping `brain.default` to `ollama:llama3.2` requires no code change.
