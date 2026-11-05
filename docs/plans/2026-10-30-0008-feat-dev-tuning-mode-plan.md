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

---

## Planning Contract

Product Contract preservation: Product Contract unchanged.

### Key Technical Decisions

- **KTD1. Dev session lives in a state file, not the owner's config.** On, off, the start time and the count of completed runs go in a daemon-owned file in the data dir, never in `config.toml`. A new mutating IPC command (`dev`, with on, off and status) and CLI verbs (`wispd dev on|off|status`) change it. The fifth completed run turns the session off (R1). While on, the Dev tab shows and tracing is on, read from the session rather than written to config, so turning it off restores the owner's settings exactly (R2).
- **KTD2. A run is an in-daemon runner over typed turns.** `wispd dev run <list>` sends a mutating `dev_run` command. The daemon starts one runner thread. For each task it begins a turn and calls the pipeline's typed entry with a per-run config copy and **no confirmation channel**, the same as today's typed path minus the owner's broker. A confirm step then comes back as skipped, and that is recorded as `stopped` (R5). Nothing changes in `act.py`, `route.py` or `stage_route.py`.
- **KTD3. Safety in a run is enforced, not trusted to the task text.** The run's config copy denies text entry, key presses, shell, external calls, posting and closing windows. A step that needs one of those ends the task as `stopped`. Tasks whose route pre-screens as agent, learn, setting, walkthrough or dictation are skipped as `stopped` before they run. Clicks (navigation) and the native `media` and `tab` tools stay allowed (R5, R6).
- **KTD4. Each run is independent.** The run's config copy turns off trajectory feedback into the act prompt, so A/B arms and repeat runs don't learn from each other. Tracing stays on (R13).
- **KTD5. The judge is new code on the existing vision-check pattern.** After each task, a privacy-vetted screenshot plus the goal and the step list go to a cheap vision model. It answers strict JSON: an outcome from the four (R8) and a one-line reason. The call goes through a run-only provider whose key reference is `omaseal://openrouter/orchestral`, the eval key (R14), with no fallback to the default key. A per-run spend cap (default $1) stops judging, not the run, and the report says so.
- **KTD6. Judge labels never enter labels.jsonl.** Each run writes its own record store in the data dir: one line per task with goal, turn id, steps, judged outcome and reason, drift flag, cost and stage times. Owner spot-checks (`wispd dev review`) show a sample and write the owner's choice through the existing turn-scoped `label` path, so the gate counts owner labels only (R9, R10).
- **KTD7. Drift is a narrow, measurable flag.** A task is flagged `suspected drift` when it names an app with a saved app skill and a step failed verification, or it needed wrong tries with a re-aimed click. The flag records what wisp did next and whether the task still succeeded (R11). Structural expected-versus-actual matching stays with lessons and is out of scope.
- **KTD8. Reports and A/B are reads over run stores.** `wispd dev runs [--json]` (a read command) returns run summaries and per-task rows, including accuracy, the outcome mix, drift, cost and time. `--vs key=value` runs the list a second time with one config-copy override (the act brain model, for example) and pairs results per task. Nothing changes the owner's config (R12, R13).
- **KTD9. Dev mode on is visible.** The bar pill gains a small "dev" badge while a session is on, as a new rule in its state mapping. The panel shows it beside the existing LOCAL badge (R3).

### Assumptions
- Text entry is denied in runs, so tasks like "search YouTube for X" end `stopped`. Lists start with open, find, navigate, tab and media tasks.
- Three modules still read the default OpenRouter key by name: grounding, the route model call and recall. Their spend in a run bills the default key and is reported as such.
- Leaf modules that re-read config from disk (trace flag, capture blocking, redaction, recall) ignore the run copy. That is acceptable, since none of them is an A/B dimension.

### Sequencing
U1, then U2, then U3, then U4, then U5. U6 can go anywhere.

---

## Implementation Units

### U1. Dev session switch
**Goal:** Turn dev mode on and off, count runs, and turn off after five.
**Requirements:** R1, R2, R3 (state side).
**Files:** new `wisp/devsession.py`, `wispd` dispatch (the `dev` command), `wisp/ipc.py` (`dev` in MUTATING_CMDS), `wisp/cli/` (`dev on|off|status`), `wisp/state.py` (a `dev` field: on and runs left), `docs/IPC_CONTRACT.md` (command and state rows), the CLI help goldens, `tests/test_devsession.py`, `tests/test_ipc_authz.py`.
**Test scenarios:**
- on, then status, then off round-trips;
- the count reaches 5 and the session turns itself off;
- turning off restores tracing and Dev tab visibility to the owner's own settings;
- a spawned agent peer is refused (mutating);
- state publishes `dev`.
**Verification:** IPC fixture and `rs/` unchanged.

### U2. Task-list runner
**Goal:** Run a task list as typed turns with safety enforced, and record each task.
**Requirements:** R4, R5, R6, R7, R8 (record half).
**Files:** new `wisp/devrun.py`, `wispd` dispatch (`dev_run`, `dev_stop`), `wisp/ipc.py`, `wisp/cli/` (`dev run <file>`, `dev stop`), `docs/IPC_CONTRACT.md`, `tests/test_devrun.py`, replay-style tests using the existing harness patterns.
**Approach:** per KTD2, KTD3 and KTD4. One run at a time. Tasks are read from a plain text file, one per line, with `#` comments. Outcome before judging: success when the turn ends ACTED; stopped on skip, refusal, a denied tool or a pre-screened route; incomplete on budget or interrupt. Each task line goes to the run store (KTD6).
**Test scenarios:**
- a 3-task list runs 3 turns in order with no confirmation channel;
- a task whose step needs confirmation ends `stopped`;
- a task needing `type_text` ends `stopped`;
- an agent-routed task is skipped `stopped` and never runs;
- `dev stop` ends the run after the current task, and the report still covers finished tasks;
- a run while the session is off is refused;
- a completed run decrements the runs left.
**Verification:** no edits to `act.py`, `route.py` or `stage_route.py`.

### U3. Judge and spot-check
**Goal:** Judge each task with a cheap vision model on the eval key, and let the owner confirm a sample.
**Requirements:** R8, R9, R10, R14.
**Files:** new `wisp/devjudge.py`, `wisp/devrun.py`, `wisp/cli/` (`dev review`), `tests/test_devjudge.py`.
**Approach:** per KTD5 and KTD6. The judge model is a run setting with a cheap default (a Gemini Flash-class vision model via OpenRouter). A strict-JSON parse failure is recorded as `unjudged`. `dev review` shows up to N (default 5) judged tasks per run, mixing successes and failures. Confirm or flip goes through `label` with the task's turn.
**Test scenarios:**
- the judge request uses the eval provider, never the default key (stubbed brain);
- a malformed reply gives unjudged;
- the per-run cap stops judging and marks the rest unjudged;
- the screenshot is the vetted capture, so a sensitive window is blanked;
- `dev review` confirm writes a turn-scoped owner label and flip writes the opposite;
- judge outcomes never appear in labels.jsonl.
**Verification:** keyless suite; no network in tests.

### U4. Drift, reports and A/B
**Goal:** Flag suspected drift, and summarize runs and paired A/B runs.
**Requirements:** R11, R12, R13.
**Files:** `wisp/devrun.py`, new `wisp/devreport.py`, `wispd` (the `dev_runs` read command), `wisp/ipc.py` (READ_CMDS), `wisp/cli/` (`dev runs`, and `dev run --vs`), `docs/IPC_CONTRACT.md`, `tests/test_devreport.py`.
**Approach:** per KTD7 and KTD8. Apply the same redaction rule devlog uses for agent peers.
**Test scenarios:**
- drift is flagged when an app-skill task has a failed verification;
- drift is not flagged without an app skill;
- a report's accuracy and outcome mix match its records;
- `--vs brain.default=X` runs twice and pairs per task, and the owner config file is unchanged;
- a spawned agent peer gets the report with goals and reasons blanked.

### U5. Dev badge and Runs in the Dev tab
**Goal:** Show that dev mode is on, and show runs in the existing Dev tab.
**Requirements:** R3, R12 (UI).
**Files:** `shell-plugin/lib/bar.js`, `shell-plugin/components/BarPill.qml`, `shell-plugin/Panel.qml`, `shell-plugin/components/DevTab.qml`, `shell-plugin/lib/dev.js`, `shell-plugin/WispService.qml` (a one-shot `dev runs` load on tab open and refresh; the Dev tab shows when the session is on or `[dev] panel` is true), `tests/qml/harness/FixtureService.qml`, scenes, goldens, `tests/test_dev_tab.py`, and bar tests.
**Test scenarios:**
- the pill shows the dev badge only while the session is on, idle included;
- the Dev tab appears when the session is on even if `[dev] panel` is false;
- the Runs section renders the latest run summary, and is empty with no runs;
- no new timer in components/.

### U6. Starter task list
**Goal:** A safe starter list for the first runs.
**Requirements:** R4, R6.
**Files:** new `docs/dev-tasks/starter.txt`, `docs/DEV_MODE.md` (how to run, review and compare).
**Approach:** About 10 safe tasks: the TLY-430 tasks ("pause youtube", "open my stripe tab"), plus open, find, navigate, workspace and media tasks drawn from the owner's misses.
**Test expectation:** a docs lint test, and a test that every starter line pre-screens as a non-skipped route.

---

## Verification Contract

- Keyless suite: `env -u OPENROUTER_API_KEY -u GROQ_API_KEY HOME=$(mktemp -d) PYTHONPATH=tests python3 -m unittest discover -s tests`. The known local failure is `test_snap` `WhatsNewCard__headline`; the known CI flake is `test_hypr` bind_clash timeout.
- `python3 scripts/assets/gen_settings.py --check` and `gen_copy.py --check`; `python3 scripts/ui/snap.py check`.
- `rs/` and `tests/fixtures/ipc_commands.jsonl` stay byte-identical, and `act.py`, `route.py` and `stage_route.py` stay untouched.
- Owner live check: `wispd dev on`, then `wispd dev run docs/dev-tasks/starter.txt`, then `wispd dev review`, then `wispd dev runs`.

## Definition of Done

- Every unit's tests pass, and the PR's CI is green.
- A starter run completes unattended on the owner's desktop, ends with a report, and the session counts it.
- No judge label is ever in labels.jsonl. The gate moves only through owner-confirmed labels.
- No abandoned-attempt code remains in the diff.
