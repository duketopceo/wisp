---
title: "feat: Dev tuning mode — an accuracy lab that turns itself off"
date: 2026-10-30
type: feat
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
origin: owner brainstorm 2026-10-29/30 (session); Tallyline TLY-427
---

# feat: Dev tuning mode — an accuracy lab that turns itself off

## Goal Capsule

- **Objective:** The owner can turn on a temporary dev mode, let wisp work through safe task lists on the real desktop, and come away with a trustworthy per-task accuracy report (what was asked, what wisp did, how it ended, where a skill drifted) that tells them what to tune next — so wisp's right-first-time rate climbs toward the v1 gate.
- **Scope boundary:** This plan owns dev tuning mode only. Install-everywhere and wisp.casa, the three.js landing page (wisp.observer), and the GUI rework are separate pieces under TLY-427 and are not active scope here.
- **Authority:** Owner decisions in this brainstorm (Key Decisions) win over defaults. Roadmap order (`docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md`) still governs act-quality work, which this plan feeds but does not change.
- **Stop conditions:** Stop if the work needs model training, a local model, a non-Linux platform, destructive tasks run unattended, or edits to `rs/`.

---

## Product Contract

### Summary

A dev mode the owner switches on by hand and which switches itself off after five runs. A run is one pass over a task list that wisp performs itself on the live desktop, limited to safe tasks. Each task is judged by a cheap vision model (the owner spot-checks) and recorded as goal, steps, and outcome, with a flag when a saved skill no longer matched the screen. Each run ends in a report, and the same task list can be run against two models or settings to compare.

### Problem Frame

Wisp's right-first-time rate is 27% (7 of 26 labelled turns) against a 60% gate that needs 50+ labelled turns, and only 7% of 325 finished turns have any label. Labels come only from the owner tapping after real use, so data accrues slowly and misses are hard to compare across changes. The owner's goal is accuracy: when you speak to your computer it does the thing, and keeps doing it when an app changes under a skill (e.g. Gmail moves a button). There is no repeatable way today to measure a task before and after a change. A live run on 2026-10-30 (TLY-430) also showed failures a repeatable run would have caught at once: every click failing on a stale cua driver socket, the microphone transcribing a playing video, and a pixel-driven "pause YouTube" instead of an Omarchy-native media command.

### Requirements

**Switching**
- R1. The owner turns dev mode on by hand (CLI and a visible switch on the existing surfaces); it stays on until turned off or until five runs have completed, then turns itself off.
- R2. While dev mode is on, full tracing and the local Dev tab are on; when it turns off, they return to the owner's normal settings.
- R3. Dev mode being on is visible at a glance wherever wisp shows status, so it is never on by accident.

**Runs**
- R4. A run is one pass over a task list (plain spoken-style tasks such as "open my Stripe tab", "pause YouTube") that wisp performs itself on the owner's live desktop and logged-in apps.
- R5. Task lists may contain only safe tasks: open, find, read, navigate, and media/window control. A task that reaches any step needing confirmation, or that would send, buy, delete, or post, ends as `stopped` without waiting for the owner.
- R6. Tasks exercise Omarchy-native skills first: media through the system media controls, windows and workspaces through the compositor, Omarchy commands where they exist; pixel clicks are the fallback the record makes visible.
- R7. The owner can stop a run at any time, and a stopped run still produces its report for the tasks it finished.

**Records and judging**
- R8. Each task records the goal, the steps wisp took, and one outcome: `success`, `stopped`, `incomplete`, or `wrong tries` (reached the goal only after wrong steps).
- R9. A cheap vision model judges each task's outcome from the goal and the final screen; its label is kept distinct from owner labels.
- R10. The owner can review and confirm or flip a sample of judged tasks; the v1 gate counts only owner-confirmed labels, and reports show the judged and confirmed numbers side by side.
- R11. When a saved skill's expected step no longer matched the screen, the task is flagged as skill drift, with what wisp did next and whether it recovered.

**Reports and comparison**
- R12. Each run ends in a report: accuracy per task, the outcome mix, drift flags, cost, and time per stage, readable in the Dev tab and from the CLI.
- R13. The owner can run the same task list against two models or settings and see which did better per task; nothing in wisp's configuration changes automatically.
- R14. Judge and comparison spend bills the dedicated eval key and stops at its cap.

### Key Decisions

- Auto-judge with owner spot-checks (session-settled: user-directed — chosen over auto-judge only, owner-prompted labelling, and scripted rule-checked runs: fastest path to labelled data while keeping the gate honest). Governs R9, R10.
- Skill drift is detected and recorded only (session-settled: user-directed — chosen over auto-fixing skills from recoveries and over leaving drift out: a wrong recovery must not teach a broken skill; smarter recovery belongs to act-quality work fed by this data). Governs R11.
- Manual on, auto-off after five runs (session-settled: user-directed — chosen over a timed session, manual-only, and per-run-only). Governs R1.
- A run is a task list wisp drives itself (session-settled: user-directed — chosen over recording the owner's real use and over offering both). Governs R4.
- Live desktop, safe tasks only (session-settled: user-directed — chosen over live desktop with any task and over a sandbox VM). Governs R5.
- Report plus model A/B, owner decides changes (session-settled: user-directed — chosen over report only and over auto-applying the winner). Governs R12, R13.
- Skills are Omarchy-native for now (session-settled: user-directed — stated after the 2026-10-30 live run: native controls before pixels). Governs R6.
- "Learning" means tuning prompts, skills, and model choice, not training a model (carried forward: roadmap "Not doing: model training").
- Linux/Omarchy only, hosted models only (carried forward).

### Scope Boundaries

- Out: making act recovery smarter when apps change (Phase 9 act quality, fed by R11's data); fixing the live-run failures themselves (TLY-430); install-everywhere, wisp.casa, the landing page on wisp.observer, the GUI rework (TLY-427 siblings); real-use recording runs; sandbox VMs; automatic config changes.
- Considered and not built: a timed auto-off (owner chose a run count); auto-applying the A/B winner (owner decides).

### How This Work Fits Together

TLY-427 holds four pieces: this dev mode, install everywhere on wisp.casa, a three.js landing page on wisp.observer, and a simpler GUI. Dev mode comes first because its data (which surfaces and steps matter) informs the GUI rework, and its runs move the gate. TLY-430's failures are the first things a dev-mode run should surface and then confirm fixed.

### Success Criteria

- A dev-mode run of a 10-task safe list completes unattended and produces a report with a judged outcome for every task.
- Within a week of use, the owner has 50+ confirmed labels, reaching the gate's turn floor.
- A before/after pair of runs on the same list shows the effect of one change (e.g. fixing TLY-430's click fallback) per task.

### Outstanding Questions (deferred to planning)

- Which judge model, and how its label agrees with the owner's on the spot-checked sample.
- How a task list is authored and stored, and the starter list (seeded from TLY-430's tasks and the owner's real misses).
- What sample size the spot-check asks the owner for per run.

### Sources

- Grounding dossier: existing toggles `[dev] refine`, `[dev] panel`, `[debug] trace`, `[eval] gate_rate`/`gate_min_turns`; CLI `wispd eval --misses/--unlabelled`, `wispd dev turns`, `wispd watch`, `wispd bugreport`; trace privacy rules in `docs/TRUST.md` and `tests/test_log_hygiene.py`.
- TLY-430: live run 2026-10-30 failure findings.
