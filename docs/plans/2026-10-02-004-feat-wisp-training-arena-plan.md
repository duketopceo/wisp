# Wisp Training Arena — plan

Origin: `docs/brainstorms/2026-10-02-training-arena-requirements.md` (LFG route —
brainstorm → plan). Goal: turn Wisp's act loop into a self-improving system —
every run logged, Jev grades outcome + efficiency, verified runs auto-graduate
into per-surface/per-app skills, all visible on a standalone arena page.
**No weight training** — the artifact is better prompts, recipes, and skill
libraries.

## Settled decisions (from brainstorm)

- Behavior loop only — no fine-tuning.
- Standalone arena page, not a panel tab.
- Auto-graduate (no human gate); regression demotes.

## Hard invariants

- Reuse `trajectories.jsonl`/`clicklab.jsonl` — no parallel logging stack.
- Jev (`typesafe/jev-1.13`) is both planner and judge; judging must be a
  separate, cheap structured call — never reuse the act-turn reply.
- Auto-graduation is auditable: every promote/demote writes a record.
- No Astra. No new provider deps.

## Implementation units

### U1 — Jev judge + graded records (`wisp/judge.py`, runner)
A `judge.verdict(task, steps, outcome, scoreboard) -> {success, efficiency,
note}` function: Jev (cheap model) gets the task text, the step list (tool,
arg, result), the declared outcome, and the verifier's ground truth — returns
structured JSON: did it complete? was it optimal (extra steps, wrong tools,
unneeded screenshots)? Result record gains `judge:` fields; trajectories gain
`surface` + `app` tags (dom→`browser-dom`, grim→`desktop`, plus focused app
class from harness).

Tests: verdict JSON parse, efficiency penalty for redundant steps, surface/app
tagging.

### U2 — Arena harness (`scripts/clicklab/` → suites)
`run.py --suite <name>`: suites defined in `suites.json` — `dom-basics`
(current 14), `dom-hard` (randomized element placement per run so memorized
coords fail), `composite` (multi-step: "click dot 2 then type its number into
the field"), `regression` (real trajectories replayed). Per-task reset already
exists; add per-run `surface`/`app` stamps and judge invocation per task.

Tests: suite loading, randomized layout determinism via seed, judge wired
per task.

### U3 — Surface/app-namespaced skill bank (`wisp/skills.py`, `wisp/recipes`)
Graduated artifacts named `skill_<surface>_<app>_<slug>`; `action_stats` and
telemetry bucket by (surface, app). `wispd train stats --surface browser-dom`
prints per-bucket success/efficiency.

Tests: namespacing, stats bucketing.

### U4 — Auto-graduation + demotion
On each judged run: `success && efficiency >= 0.9` increments the task-shape's
streak; streak ≥ 3 → skill auto-installed (`auto: true` flag in the skill
record). Any later failure under that skill → demote to draft + record event.
`wispd train history` lists promote/demote events.

Tests: streak counting, auto-install at threshold, demotion on failure,
event log.

### U5 — Arena page (`scripts/arena/` or `wispd arena`)
Standalone local page (static HTML + tiny stdlib server, like clicklab):
- suite picker + run trigger, live step feed (poll `state.json`/trajectory tail)
- per-task row: verdict, judge grade, ms
- trend sparkline per suite, per-surface breakdown table
- skill bank view: graduated skills, streaks, promote/demote history
Keep it server-rendered HTML/JS with no deps — "hardcore intricate" in density
and information, not framework.

Tests: server endpoints return JSON for runs/stats/skills; page smoke via
BrowserOS evaluate.

### U6 — Trajectory replay + difficulty ladder
`scripts/clicklab/replay.py`: load `trajectories.jsonl` entries, reconstruct
the task in the lab page, re-run, compare outcome. `dom-hard` suite randomizes
element positions/sizes/labels per seed.

Tests: replay produces a graded record; seeded randomization varies layout.

## Order

U1 → U2 (graded suite runs exist) → U3 → U4 (learning loop closes) → U5
(arena visualizes it) → U6 (replay/ladder).

## Risks

- Judge flakiness: Jev verdicts must be schema-locked JSON; retry once on
  parse failure, else mark `judge_error`.
- Auto-graduation runaway: streak resets to 0 on any failure; cap bank at
  50 skills per (surface,app).
- Judge cost: jev is cheap; bound to one call per task.
