---
title: "Wisp Full Roadmap — Plan (current point 2026-11-14)"
type: docs
date: 2026-11-14
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Wisp Full Roadmap — Plan

**Status (2026-11-14):** This is the consolidated roadmap plan at the current point on `master` (`d9d8022`). Authority chain: `ROADMAP.md` (live board, last synced 2026-11-08) → this plan (sequencing + links) → the child plans named below (unit detail). Historical full-roadmap plans (`2026-10-05-001-full-roadmap`, `2026-10-25-1625-heyclicky-linux-roadmap`, `2026-10-26-0031-v1-roadmap`) stay as records; they do not supersede this plan.

## Goal Capsule

- **Objective:** Ship stable `v1.0.0` on Linux, then grow HeyClicky-class retention (agents, connectors, memory, home) without regressing the v1 gate.
- **Means:** One ordered sequence: (1) finish the v1.0 gate first, (2) land the 2026-11-13 framing/security plan, (3) execute the three 2026-11-14 area plans in order, (4) keep Areas 9/11 behind evaluation data.
- **Execution profile:** Docs-only sequencing; each child plan lands as its own PRs with tests planned up front.
- **Stop conditions:** Stop and re-plan if `wispd eval` after 50 labels names a different weakest turn kind than act; stop the proxy work if TRUST.md cannot list every proxy host before code.

## Current state (master `d9d8022`, 2026-11-14)

- **Published:** `v1.0.0-rc.3` (Linux prerelease 2026-11-09). GitHub "Latest" still `v0.9.0` (RCs are prereleases).
- **Shipped:** OpenRouter-only + act router, background ACP agents, HeyClicky surfaces (points timed to speech, draw overlay, walkthroughs, per-app history, streaming STT + barge-in), 89 app skills, companion core (composer, ink, window-text answers, focused-monitor following), verified install/update, verified PID namespace cleanups.
- **v1.0 gate tally (2026-11-03):** 35 labelled turns, 9 right first time (26%). Needs ≥50 labels at ≥60%. Most labels predate recent fixes — understates the current rate.
- **Unmerged worktrees:** `feat/wisp-identity-seed-guard`, `feat/wisp-u2-u4`, `fix/voice-input-reliability`; 6 dependabot bumps open.

## Ordered sequence

| Phase | What | Child plan | Gate |
|---|---|---|---|
| 1 | Rerun gauntlet + owner reinstall/voice checks + label to ≥50 turns | `docs/plans/2026-11-01-0008-gauntlet` etc. (ROADMAP §Next) | `wispd eval` ≥60% / ≥50 |
| 2 | Clean-box `wispd onboard`/`doctor`, tag `v1.0.0` | ROADMAP §v1.0 gate | Gate checkboxes |
| 3 | Framing (untrusted-content rule), run-record index, skill/browser contracts | `2026-11-13-2336-framing-and-job-memory` (41 KB, untracked — needs a PR) | Its verification table |
| 4 | Dictation uplift + voice (Areas 3+4) | `2026-11-14-0100-dictation-voice-uplift` | U1–U3 tests + 10-turn voice eval |
| 5 | Agents + memory + home (Areas 5+7+8) | `2026-11-14-0100-agents-memory-home` | U1–U4 tests + isolated-session overlay check |
| 6 | Connectors + proxy decision (Areas 6+11) | `2026-11-14-0100-connectors-proxy-bundle` | Connector tests; TRUST.md before proxy code |
| 7 | Engine (Area 9) + macOS adapters stay experimental | Deferred brainstorm | Decision after eval gate passes |
| 8 | Clicking polish (Area 10) — grounding post-training U4–U12, UI overhaul PRs 2–7 | Already planned; runs parallel to 4–6 as data allows | Measurement ends the sequence |

## What this plan does not do

- Design any single area — child plans own unit detail.
- Change fixed decisions: OpenRouter-required, Linux first, `rs/` frozen, no decision model on routing, `wisp.observer` not yet verified.
- Claim any timeline. The gate is evidence-driven (`wispd eval` + gauntlet), not date-driven.

## Verification

- `python -m unittest tests.test_docs_lint` passes (new plan files have valid frontmatter).
- Every plan linked above exists on disk; ROADMAP.md Areas table should gain links to the 2026-11-14 plans on next sync.
