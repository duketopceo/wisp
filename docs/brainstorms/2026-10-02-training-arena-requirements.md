# Wisp Training Arena — Requirements

Date: 2026-10-02 · Status: requirements agreed via brainstorm (LFG route)

## What we're building

A **training system + standalone training page** for Wisp's act loop. Wisp runs
tasks; every step is logged; Jev grades whether the task was done *and* whether
it was done optimally; verified runs feed a self-improving behavior loop. No
model weights are trained — the artifact is better prompts, recipes, routing
biases, and per-surface skill libraries.

## Settled decisions (user-directed)

| Decision | Rejected alternative | Why |
|---|---|---|
| Behavior loop only — no fine-tuning | Fine-tune a small model on trajectories | Fast iteration, no GPU dependency, ships now |
| Standalone training arena page (served locally) | Panel tab only | "Hardcore intricate" UI needs its own surface; panel stays for live status |
| Auto-graduate verified runs to skills/recipes | Human approval gate | User wants the loop hammering unsupervised; demotion on failure is the safeguard |

## Architecture shape (product-level)

Three surfaces, one data spine:

1. **Arena page** (local web app, e.g. served like clicklab): task suites,
   live run viewer, per-task verdict + Jev grade, score trends over time,
   difficulty ladder, replay of trajectories.
2. **Harness**: extends `scripts/clicklab/` — task generators, per-surface
   suites (browser-DOM, linux-desktop, per-app), self-grading checks plus a
   Jev judge pass for "optimized or not" (extra steps, retries, wrong tools).
3. **Learning loop**: graded trajectories → per-surface/per-app skill bank
   (extends `recipes`/`action_stats`) → auto-graduation with demotion on
   regression.

## Functional requirements

- **Everything logged**: every tool call, result, coordinate, ms, model reply —
  trajectories already do this; arena consumes them, no parallel logging stack.
- **Jev is the judge and the planner**: act runs plan with Jev today; grading
  adds a second Jev pass per task — `did it complete?` + `was it optimal?`
  (extra steps / wrong tools / unnecessary screenshots). Output: `success`,
  `efficiency` score, `verdict note` appended to the result record.
- **Surface differentiation**: every task/run carries a `surface` tag —
  `browser-dom`, `desktop-real`, `desktop-guide`, and per-app (e.g.
  `godot`, `foot`, `chromium`). Stats and learned skills bucket by
  `surface` + `app` so per-app expertise accumulates.
- **Per-app saved skills**: verified trajectories graduate into
  `skill_<surface>_<app>_<task-shape>` entries the act loop can replay;
  a run that later fails under a graduated skill demotes it (back to draft,
  counted in stats).
- **Arena page** shows: task suite list, run history, live step feed during a
  run, per-task outcome + Jev verdict, success-rate trends per surface,
  auto-graduated skill list with demote/promote events.
- **Difficulty ladder**: suites scale from fixed-target clicking →
  scroll/type/select → multi-step composite tasks → unseen layouts
  (randomized element placement per run) to prevent memorized coords.
- **Real-usage ingestion**: production `trajectories.jsonl` entries can be
  replayed in the arena as regression tasks.

## Non-goals

- No model fine-tuning / weight updates (future option, not this work).
- No new logging backend — reuse `trajectories.jsonl` + `clicklab.jsonl`.
- No cloud training service; all local.
- Not a panel tab (panel keeps live-status only).

## Success criteria

- Arena runs a suite headlessly (`run.py --suite <name> --dom`) and produces
  a graded report: per-task success, Jev efficiency verdict, aggregate trend.
- A repeated suite shows a measurable improvement path (graduated skills,
  fewer steps on repeats).
- Per-surface stats are queryable (`wispd train stats --surface browser-dom`
  or equivalent).
- Auto-graduated skills visibly fire in subsequent runs (`skill_*` tool calls
  in trajectories).

## Open areas for planning

- Arena serving stack: static page + JSONL file reads vs. small HTTP server.
- Jev judge prompt/schema (success + efficiency rubric).
- Skill naming/namespacing scheme (`skill_browser-dom_chromium_click-*`).
- Whether arena runs inside BrowserOS page or a standalone webview.
- How randomized-layout tasks generate (seeded task generator in clicklab).
