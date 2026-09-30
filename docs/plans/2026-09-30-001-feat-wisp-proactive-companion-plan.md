---
title: "Wisp proactive companion: sense layer, suggestions, runtime autodetect, seeded skills"
date: 2026-09-30
status: draft
---

# Wisp Proactive Companion Plan

## Problem frame

Wisp is purely reactive today: hold SUPER+D, speak, it responds. The
Clicky-parity gap is the **proactive loop** — watch work patterns, notice
repetition, pop a floating card asking "automate this?" Requirements from
the user:

- No runaway processes — hard guardrails on everything autonomous.
- Agent runtime defaults to opencode but should **autodetect** what
  exists (`codex`, `claude`, `devin`, …) rather than hardcode.
- Seed skills on install: a local dayflow bridge/checkup skill, plus an
  importer to pull in the luke-agents skill set.
- Surfaces everywhere: GUI, TUI, omarchy bar plugin that pops out while
  working, orb suggestion cards.
- Cheap and constant: use dayflow's already-summarized journal + Jev for
  classification; a cheap vision/text model only at inference time.
  Never stream-tokens-in-a-loop.

## How Clicky likely does it (and the honest answer)

Nobody outside the vendor knows its internals. The economically sane
design — and the one this plan assumes — is **log passively, infer in
batches**: local event capture costs nothing, a small model reviews a
day's blocks periodically, and a bigger model only runs when the user
engages. That is exactly what dayflow already does for activity capture,
which is why the observer half of this feature should not be rebuilt —
it should be *read*.

## Architecture decision

Two new threads inside `wispd` (Python core first, Rust parity after),
both budgeted and kill-switched:

1. **`sense` collector** — appends a compact activity record to
   `activity.jsonl` on a slow tick (default 300s). Sources, in order of
   cheapness: `hyprctl activewindow -j` (free, local), `dayflow today
   --json` block tail (already summarized — text, not pixels). No
   screenshot harvesting; vision models only run inside the existing
   `answer`/`act` routes.
2. **`suggest` miner** — on a slower tick (default 45min, plus on daemon
   idle), sends the last N hours of `activity.jsonl` + dayflow cards to
   the configured cheap model asking for recurring sequences. Output is
   JSON → `suggestions.jsonl`. Jev (typesafe `jev-1.13`) does a cheap
   pre-filter pass: "is this window of activity worth mining?" so the
   chat model only runs when there's signal.

Both ticks are `threading.Timer`-style loops inside the daemon, not
spawned processes — nothing to run away. Guardrails are a dedicated
unit (S6), not a sprinkle.

## Cost posture

| Layer | Model | Cost shape |
|---|---|---|
| Activity capture | none (hyprctl/dayflow files) | free, local |
| Mine-worthiness gate | `typesafe/jev-1.13` | cents, typed output |
| Pattern inference | `[sense] model` — default `google/gemini-2.5-flash`, configurable to a local Gemma via Ollama/MLX | one call per tick, batch text |
| Suggestion → automation | act loop on the user-picked answer | only on approval |

`[sense] model` accepts any provider the brain already supports —
`openrouter:…`, `ollama:gemma3:27b`, `mlx:…`. Gemma-class local models
are the zero-marginal-cost option once Ollama/MLX is configured.

## Implementation units

### S1 — Sense collector (`wisp/sense.py`, `wispd`)

- `Sense.tick()`: reads `hyprctl activewindow -j` → `{ts, app, title}`
  delta; every Kth tick pulls `dayflow timeline --json` tail and stores
  the newest block summaries. Appends to
  `~/.local/share/wisp/activity.jsonl` (rotated, capped ~2MB).
- Config: `[sense] enabled=false, interval_s=300, dayflow=true`.
- Runs as a daemon thread; errors are logged to `wispd.log` and
  swallowed — a broken sense loop must never kill the daemon.
- *Tests:* `tests/test_sense.py` — tick writes delta records, survives
  missing dayflow/hyprctl, honors `enabled=false`, file rotation cap.

### S2 — Suggestion miner (`wisp/suggest.py`, `wispd`)

- On `[sense] mine_every_s=2700`: read activity window → Jev
  yes/no "worth mining" → cheap-model prompt returns JSON
  `{suggestions:[{title, trigger, routine, est_steps}]}`
  → `suggestions.jsonl` with dedup key (trigger+routine hash) and a
  `snoozed`/`never` list persisted in `~/.config/wisp/never.json`.
- New suggestion → `state.transition("suggestion", suggestion=…)` — the
  orb card pops "Automate this? [yes] [no] [never]" via the existing
  choices IPC (`choice` cmd gains `suggestion:*` labels).
- Approving a suggestion runs the act loop on the routine text (fully
  gated); a suggestion can also author a reusable skill via the learn
  prompt path.
- *Tests:* dedup, never-list suppression, Jev-gate short-circuit saves
  the model call, approve→act handoff, malformed JSON discarded.

### S3 — Surfaces (GUI, TUI, bar, orb)

- **Orb/card**: `suggestion` status + buttons (yes / not now / never).
- **Bar widget**: badge dot while `status=acting|suggestion`; popup
  already shows activity — add a "suggestions" line.
- **GUI**: new Activity tab — `activity.jsonl` sparkline + suggestions
  list with approve/dismiss buttons.
- **TUI**: `wispd tui` — stdlib curses dashboard: live status, recent
  decisions, suggestions, labels. No new deps.
- *Tests:* state JSON carries suggestion payload; TUI renders headless
  (one-frame smoke); GUI is QML — manual verify + log grep.

### S4 — Runtime autodetect (`wisp/agents.py`, `wispd doctor`)

- `agent_runtime = "auto"` (new default): probe PATH in priority order
  `opencode → codex → claude → devin`, cache first hit per daemon run.
- `wispd doctor` (new subcommand): prints detected runtimes, STT engine,
  whisper model presence, brain provider, allow_shell/risk gates,
  dayflow/hyprctl reachability — the "scan for all those harnesses" the
  user asked for.
- *Tests:* `tests/test_agents.py` add — auto mode picks highest-priority
  available binary, explicit config overrides, missing runtime → clear
  SKIP.

### S5 — Seeded skills (`wisp/skills_seed/`, `wispd skills import`)

- Bundle `wisp/skills_seed/dayflow-bridge/SKILL.md` (how to query
  timeline/cards/insights/agent sessions via `dayflow … --json`) and
  `wisp/skills_seed/self-checkup/SKILL.md` (read wispd.log, trace,
  decisions, labels → health digest). Install seeds them into
  `~/.local/share/wisp/skills/` if absent.
- `wispd skills import <dir>` — copies `*/SKILL.md` trees (e.g.
  `~/Documents/github/personal/luke-agents/_LUKE`) into the skills dir;
  `wispd skills import --list` previews names first. No symlink — a
  copied snapshot with provenance line.
- *Tests:* seed-on-install is idempotent, import skips existing,
  provenance comment written.

### S6 — Guardrails (`wisp/agents.py`, `wispd`, docs)

- `[agent] max_concurrent=3`, `task_timeout_s=1800` — watchdog reaps
  expired tasks, orphan scan on daemon start kills tasks whose parent
  wispd died.
- Suggestions never auto-execute: approval path only; `never` persists.
- Sense/suggest loops: single-flight (a tick can't overlap itself),
  max output capture, total budget `[sense] max_calls_per_day=48` —
  counter resets at midnight local, logged to `wispd.log`.
- *Tests:* concurrency cap refuses 4th spawn, timeout reaper,
  suggestion requires explicit approval, call-budget halts mining.

## Sequencing

S1 → S6 skeleton (guardrails land with the collector, not after) →
S2 → S4 → S5 → S3 surfaces. Rust parity follows Python once the Python
loop proves itself in the soak — the running daemon is Python.

## Out of scope

Wake word, continuous screenshot observation, per-pixel vision loops,
automatic execution of suggested routines (approval-only by design).
