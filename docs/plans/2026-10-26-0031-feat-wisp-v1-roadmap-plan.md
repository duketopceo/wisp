---
title: Wisp v1 Roadmap - Plan
type: feat
date: 2026-10-26
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Wisp v1 Roadmap - Plan

## Goal Capsule

- **Objective:** On this Hyprland/Omarchy machine, with only hosted model keys, the owner holds the hotkey, speaks, and Wisp answers by voice while pointing and drawing on screen, walks through tasks, and runs routines — right first time often enough to clear the owner's v1.0 bar in `wispd eval`.
- **Means:** Ship the running daemon from `master` first, then spend effort where the eval says turns fail (act quality), then add the HeyClicky surfaces, and leave cleanup that no user feels for last (KTD1).
- **Authority:** Supersedes `docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md` for every phase not yet shipped. That plan stays the record for Phases 1–4.
- **Execution profile:** Each phase is its own PR, planned from this roadmap when it starts. This plan's own unit (U1) is documentation only.
- **Stop conditions:** Re-plan if `wispd eval` shows a different weakest turn kind than act once 50 turns are labelled.
- **Who finishes:** U1 by this PR; phases by follow-up runs.

---

## Product Contract

### Summary

Phases 1–4 are on `master`. The rest of v1 is reordered by what moves the first-time-correct rate: redeploy, make install and speech-to-text hosted by default, fix act-turn failures, wire the HeyClicky surfaces, then replace the Jev router with a regex fast path and finish agent hardening.

### Problem Frame

Shipped (merged 2026-10-25/26): #139 OpenRouter-only defaults and the act router; #141 agent IPC authz, truthful task outcomes and routines; #142 CI flake root causes; #143 Linux-only; #144 training stack removed and `wispd eval` added.

None of that runs on the owner's desktop yet: the daemon installed at `~/.local/opt/wisp` is an Oct 21 build. The current eval (19 labelled turns) puts first-time-correct at 32%, act turns at 3 of 11 with 7 needing a retry.

The Jev decider earns nothing on this traffic: over 692 routed turns (Oct 4–26) Jev agreed with the free regex heuristic on 690 of the 691 it answered. No pplx-decider data exists (the shadow decider never ran here). With `router = "act"` the hop is already off the hot path, but bare launches now pay for a full act loop.

### Key Decisions

- **Product target is HeyClicky core plus agents.** Governs R5–R8. (session-settled: user-directed — chosen over "HeyClicky core only" and "keep full autonomy first".)
- **Hosted models only; local model servers opt-in and off.** Governs R2. (session-settled: user-directed — chosen over keeping the local/OpenRouter toggle.)
- **Linux only.** (session-settled: user-directed — chosen over "Linux first, keep seams".)
- **One end-to-end eval is the v1 gate.** Governs R9. (session-settled: user-directed — chosen over keeping the training/per-route soak stack.)
- **`rs/` frozen.** (session-settled: user-directed — chosen over deleting it or keeping parity.)
- **No decision model on the routing path.** Neither Jev nor the pplx decider; the heuristic becomes a fast path in front of act. Governs R10. Recommended from the route A/B data above; the owner asked the question and has not overruled it.

### Requirements

**Ship what exists**

- R1. The running daemon matches `master`, and redeploying is one command from a git ref.
- R2. A fresh Omarchy box with hosted keys only answers a spoken question: speech-to-text defaults to a hosted provider, onboarding asks for the keys it needs, and `wispd doctor` passes with no local services.

**Make turns right first time**

- R3. The top act-turn failure patterns in the labelled data are fixed — starting with default-app resolution ("open my email" focusing BrowserOS), wrong-coordinate clicks, and launch-instead-of-navigate.
- R4. Each fix is proven by a replay fixture or a labelled re-run, and `wispd eval` moves.

**HeyClicky surfaces**

- R5. Points fire as their sentence starts playing, from one answer stream.
- R6. Wisp draws rings, arrows and highlights from the answer stream and clears them when speech ends.
- R7. Walkthroughs speak a step, point at the target, detect the action, and advance; pointing snaps to the labelled element first.
- R8. Chat context is per app; screenshots are skipped for sensitive windows; speech-to-text streams while the key is held, and talking over Wisp interrupts it.

**Gate and cleanup**

- R9. v1.0 ships when `wispd eval` passes `[eval] gate_rate` over at least 50 labelled turns and the clean-box check (R2) passes.
- R10. The Jev router, shadow decider, decision replay and route A/B are gone; a regex fast path sends unambiguous launches and plain questions straight to their handler and everything else to act.
- R11. Spawned agents run with a scrubbed environment (no Wisp-held credentials).

### Success Criteria

- `wispd eval` reports PASS with the owner's `gate_rate`.
- A bare "open firefox" completes without an act loop.

### Scope Boundaries

**Deferred to Follow-Up Work:** every phase below is its own PR.

**Outside v1:**
- Journaled file organize with voice undo, skills export, and the deferred-auth connect handshake (clacky extras with no v1 requirement).
- Two-stage VLM grounding (H3) unless Phase 9's data shows grounding is the act bottleneck.
- Local-first operation, model training, cross-platform ports.

### Outstanding Questions

- Q1 (owner). The v1.0 pass rate. Recommendation: `gate_rate = "60%"` now (current 32%), raised after Phase 9.
- Q2 (owner). Which clacky extras to keep. Recommendation: keep streaming speech-to-text and barge-in (R8); drop the three listed under Outside v1.
- Q3 (Phase 5). Replace the `jev` grounding fallback with an OpenRouter vision point call, or drop it.
- Q4 (settled). Groq is the hosted speech-to-text default (owner, 2026-10-26, shipped in #146).

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Order by what the eval can see.** Redeploy before anything else so new labels measure `master`; act quality (Phase 9) before HeyClicky surfaces (Phase 7) because act is the weakest kind with the most turns; Jev removal (Phase 5) after the surfaces because it is invisible to the owner except as a launch-latency win.
- KTD2. **Phase numbers keep their original meaning** (from the superseded plan) so PRs, commits and Tallyline issues stay traceable; only the order changes.

### Phased Delivery

Order of work, top to bottom. Each row is one PR.

| Order | Phase | Delivers | Requirements | Size |
|---|---|---|---|---|
| 1 | 0 · Redeploy | Install `master` to `~/.local/opt/wisp`, restart `wispd`, confirm a spoken turn; set `gate_rate` once Q1 is answered | R1 | S |
| 2 | 6 · Hosted install | Hosted speech-to-text default (Q4), onboarding asks for keys, soft-fail on key lookup, `wispd install` redeploys from a git ref, clean-box check | R1, R2 | M |
| 3 | 9 · Act quality | Fix the top act failure patterns from `wispd eval` and the labels; one replay fixture per pattern | R3, R4 | M |
| 4 | 7 · HeyClicky surfaces | Single-stream pointing timed to speech, draw overlay, walkthrough with label-first snap, per-app history, sensitive-window skip, streaming STT, barge-in | R5–R8 | L |
| 5 | 5 · Router fast path | Remove Jev router, shadow, replay and route A/B; promote the heuristic to a fast path in front of act; resolve Q3 | R10 | M |
| 6 | 8 · Agent hardening | Spawn-env scrub | R11 | S |

### Assumptions

- Labelling continues at roughly today's pace, so 50 turns accumulate during Phases 6–9.
- The three known act failure patterns are still the top ones once the redeployed daemon has been used; Phase 9 re-ranks from `wispd eval` before fixing.

---

## Implementation Units

### U1. Roadmap of record

- **Goal:** The repo's roadmap reflects this plan and the current eval.
- **Requirements:** KTD1, KTD2.
- **Files:** `ROADMAP.md`, `docs/ROADMAP.md`, `docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md` (supersession notice only).
- **Approach:**
  1. `ROADMAP.md`: shipped phases with PR numbers, remaining phases in the new order, the v1.0 gate, the current `wispd eval` tally line, and the open owner decisions.
  2. `docs/ROADMAP.md`: point at this plan.
  3. Old plan: one-line supersession notice at the top linking this plan.
- **Test expectation:** none -- documentation; docs lint must pass.
- **Verification:** `python3 -m unittest tests.test_docs_lint` passes.

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Docs lint | `python3 -m unittest tests.test_docs_lint` | U1 |

---

## Definition of Done

- `ROADMAP.md` lists shipped and remaining phases in this plan's order with the current eval tally.
- The superseded plan points here.
