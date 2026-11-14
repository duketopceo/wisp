---
title: "feat: Persistent agents, memory system, and home surface — Clicky personas lite"
type: feat
date: 2026-11-14
depends_on: docs/plans/2026-11-08-1749-feat-wisp-companion-core-plan.md
roadmap_area: 5+7+8
---

# Persistent agents, memory system, and home surface

## Goal Capsule

- **Objective:** Give Wisp the retention layer HeyClicky calls Clickys: named persistent agents with faces/names, a full memory system, and one home surface — without copying HeyClicky's look.
- **Means:** Extend `wisp/agents.py` (named ori-opencode tasks, `agent_home.py` per-agent `AGENTS.md`/`notes/`/`output/`/`tmp/`) + `wisp/memory.py` (`MEMORY.md`/`USER.md` + `VOLATILE.md`) + new home panel in `shell-plugin/`. No UIs beyond one home surface.
- **Authority:** Sonar-verified 2026-11-14 against heyclicky.com/changelog: each Clicky has own memory, chat, file folder; memory expanded 20→40 messages; progress cards expose working files with Stop/Retry; background delivery; routines quiet-landing; suggestions: 6 a.m. gate, holds during call/share/Focus, 3 unopened mornings → break, 3-day dismiss → 5-day rest. Wisp keeps its own classical-literature agent names (roadmap decision).
- **Stop conditions:** Stop if home surface needs notch/camera positioning (Omarchy notch is a design fork, not the product default); do not add ambient routing until one home surface exists.

## Requirements

- **R1 (named agents).** Every `wispd agent` task has a stable name, `AGENTS.md` home, per-agent `notes/` + `output/`; follow-ups resume the named thread; progress card (in Panel) shows files + Stop/Retry (`agents.py` + `shell-plugin/Panel.qml`).
- **R2 (memory system).** `VOLATILE.md` expiry + promotion already exists (H8); add per-run scratch index (2026-11-13 plan's run-record gap) and cap enforcement tests; `recall.db` FTS5 remains retrieval backend.
- **R3 (suggestions feed).** One card at a time: Do it / Adjust / No; decline-reason injection into next batch; morning greeting after 06:00; holds on call/share/Focus (reuse existing call/share detection); backoff = fixed 7-d `suggest_policy.PAUSE_DAYS` (documented simplification vs HeyClicky's 5-d; revisit if eval labels justify).
- **R4 (home).** One home surface: chats + agents + suggestions + routines in one Panel view; resizable, remembers size; drag-out of produced files.

## Units

| ID | Work | Files | Test |
|---|---|---|---|
| U1 | Named-agent persistence + progress card with files/Stop/Retry | `wisp/agents.py`, `wisp/agent_home.py`, `shell-plugin/Panel.qml` | `tests/test_agents_home.py`: resume by name; stop/retry IPC round-trip |
| U2 | Run-record index (one line per run: produced + learned) rendering the home "activity" column | `wisp/agent_home.py`, `wisp/memory.py` | `tests/test_memory_index.py`: index builds from registry; promotion to `MEMORY.md` logged |
| U3 | Suggestions feed: one-card rule, decline memory, 6 a.m. + call/share/Focus holds, backoff | `wisp/suggest.py`, `wisp/suggest_policy.py` | `tests/test_heyclicky_delta.py` extended: 3-day streak → pause, hold during call, decline shifts next batch |
| U4 | Home surface (single view, size memory, drag-out) | `shell-plugin/` | `tests/browser` smoke + manual overlay check on isolated Hyprland session |

## Non-goals

- No faces/avatars in v1 of this area (names + presence first); no ambient "tell X to do Y" routing; no notch implementation.

## Risks

- Persistence invites stale-context leakage across projects — scope `notes/` per agent-home; never inject one agent's memory into another's run without explicit request.
- Card/email file exposure: produced files are user-owned outputs; default panel shows names only, open-on-request.
