---
title: "World-class onboarding and doctor — preflight, verdict, smoke, rollback"
type: feat
date: 2026-11-14
depends_on: docs/plans/2026-11-14-0200-feat-wisp-full-roadmap-plan.md
roadmap_area: 2 (Hygiene and defaults, v1 gate)
---

# World-class onboarding and doctor

## Goal Capsule

- **Objective:** Wisp's `wispd onboard`, `wispd doctor`, `wispd install` and `wispd update` meet the staged, resumable, verify-before-write standard the v1 gate requires for `v1.0.0`.
- **Means:** Four surgical PRs over existing `wisp/cli/diagnose.py`, `wisp/onboard.py`, `wisp/preflight.py` and `wisp/update.py`. No new verbs, no new daemons.
- **Authority:** Sonar-verified 2026-11-14 (gh / Homebrew / Vercel / Stripe / Linkerd class patterns): install → authenticate → readiness checks → preview → first write; doctor answers what/serious/next-fix read-only with verdict-first + machine output; installers stage → verify → activate → smoke → success-or-rollback.
- **Stop conditions:** Stop if a smoke turn needs a paid model call to prove the install (keep it opt-in and skippable offline); stop if any check writes state by default (doctor stays read-only).

## Requirements

- **R1 (onboard preview).** `wispd onboard --preview` (and final interactive step) answers the six preflight questions: what / where / account+region / permissions / failure plan / cancel path. No config write happens before it.
- **R2 (doctor verdict + path/config/whoami rows).** First render line is a verdict (`✓ healthy — 42 ok, 0 fail` / `✗ unhealthy — 2 failed`). Rows: PATH duplicates + `mise` shim-staleness, redacted effective config sources, OpenRouter `whoami` (account, region, usage cap; distinguishes not-authed vs forbidden). Per-row `try:` fix command where one exists. `--json` unchanged in shape (additive fields only).
- **R3 (offline vs server-verified).** Every `doctor` row carries `offline` or `server-verified` tag; summary states which checks are offline-only. No mandatory network for offline-capable verdicts.
- **R4 (update stage → smoke → rollback).** Stage new version in a versioned dir, verify all files, atomic swap; success line shows backup path + `wispd update --rollback` command; failure labels state honestly (`failed: kept old build`); opt-in `--smoke` round-trip turn.

## Units

| ID | Work | Files | Test |
|---|---|---|---|
| U1 | Onboard preflight summary view (read-only; snapshot of pending writes) | `wisp/onboard.py`, `wisp/cli/diagnose.py` | `tests/test_onboard.py`: preview prints 6 answers, writes nothing; interactive walk ends at preview |
| U2 | Doctor verdict line + PATH/shim, redacted-config, whoami rows; per-row fix hints | `wisp/cli/diagnose.py`, `wisp/svc.py` | `tests/test_doctor.py`: verdict line first; JSON shape additive; redaction never prints key bytes |
| U3 | Offline/server-verified tagging + summary line | `wisp/cli/diagnose.py` | `tests/test_doctor.py`: every row tagged; offline-only box still prints full verdict |
| U4 | Update stage→verify→swap + `--smoke` turn + honest failure label | `wisp/update.py`, `wisp/preflight.py` | `tests/test_update.py`: verify failure keeps old build; smoke skipped offline; success line carries backup path |

## Non-goals

- No new first-run wizard replacing `onboard`; no doctor auto-fix (fixes stay commands the user runs); no billing/metering.

## Risks

- `whoami` probing OpenRouter can trip rate limits on `doctor --live`; keep it inside `--live` only.
- Stage-swap must not break the running daemon's IPC path; overlap is handled by backing up before any file move.
