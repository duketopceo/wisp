---
title: "feat: Training gauntlet v2 — oracle scoring, Pass^k, first-fault, reviewer tier"
type: feat
date: 2026-10-03
origin: docs/brainstorms/2026-10-02-training-gauntlet-research.md
---

# feat: Training gauntlet v2 — oracle scoring, Pass^k, first-fault, reviewer tier

## Summary

Upgrades the training arena from "Jev judges vibes" to objective,
attributed, reliability-scored measurement — then adds the offline
reviewer tier that turns failures into human-approved skill candidates.

## Problem Frame

Current limits, all confirmed in live runs:

- **Efficiency is Jev's opinion** — a 1-step click scored 0.67 "clean"
  until the rubric was hand-tuned. For synthetic tasks we *know* the
  optimal sequence; efficiency should be measured, not judged.
- **No first-fault attribution** — judge says `waste=no_focus` but not
  *which step* went wrong; corrections can't attach to a position.
- **pass@1 lies** — a model that passes 1/1 and fails the next 2 looks
  perfect. Research standard is Pass^k (reliability over repeats).
- **Flakes pollute stats** — env flakes, judge false negatives, and
  genuine model failures share the same FAIL bucket.
- **No reviewer tier** — trajectories pile up with no async pass that
  extracts corrected sequences and skill candidates.

## Requirements

From origin `docs/brainstorms/2026-10-02-training-gauntlet-research.md`:

- R1: Suites carry oracle step-counts; efficiency = optimal/actual when
  an oracle exists, Jev verdict fills the gap otherwise.
- R2: Judge schema gains `first_fault_step` + `first_fault_reason`;
  runs record and display it.
- R3: `train.stats()` reports pass@1 and Pass^k per task key.
- R4: Run records classify `flake` (none|env|judge_fn|timing|model);
  arena shows the taxonomy separately from genuine failures.
- R5: `wispd review` runs an async batch over trajectories producing
  counterfactual sequences + first-fault analysis → staged skill
  candidates gated on human approval (never auto-distilled).
- R6: All fields backward-compatible — unkeyed/older records and banks
  keep working.

## Key Technical Decisions

- **KTD1: Oracle is data, not code.** `suites.json` entries gain an
  optional `"oracle"` step list — the authored minimal sequence
  (`["click(alpha)"]`). run.py counts executed tool calls vs oracle
  length; `eff = min(1, oracle_len / actual_len)` overrides Jev's
  efficiency when present. Jev still judges success + waste.
- **KTD2: first_fault is judge-emitted, verifier-confirmed.** The judge
  prompt gains "identify the earliest step that was wrong or wasteful
  (0-indexed, or -1)". On verified-fail runs without a judge call,
  first_fault falls back to the last non-error step.
- **KTD3: Pass^k keyed on (surface|suite|task|model).** stats() groups
  runs by task key + model; `pass@1` = first-seen result, `pass^k` =
  fraction of k where ≥1 run in the k-group passed — approximated as
  pass@N rate over the group (we run repeats, not samples).
- **KTD4: Flake is a heuristic classifier, not a second judge.** A pure
  function labels each run: `env` (tool ERROR infra: MCP down, page
  unreachable, screenshot fail), `judge_fn` (verified pass + judge says
  fail — disagreement), `timing` (verified fail + verdict contains
  timeout/stall with ≤2 steps), `model` (everything else). Cheap,
  testable, honest.
- **KTD5: Reviewer output is a proposals file, not bank writes.**
  `wisp/review.py` replays failures + low-efficiency runs through a
  decider-class provider (`[brain.reviewer]` or decider default), emits
  `{task, model, first_fault, counterfactual_steps, skill_candidate}`
  to `review_proposals.jsonl`. `wispd review` prints them; approval
  reuses the existing recipes/human-gate pattern — nothing auto-enters
  the bank or the prompt.

## Implementation Units

### U1. Oracle baselines in suites + objective efficiency

**Goal:** authored optimal sequences per task; efficiency measured as
ratio when oracle exists.

**Requirements:** R1

**Files:**
- `scripts/clicklab/suites.json` — `oracle` field per task
- `scripts/clicklab/run.py` — count executed steps; write `oracle_len`,
  `actual_len` on the record; objective eff overrides judge eff
- `tests/test_judge.py` or new `tests/test_oracle.py`

**Approach:** Oracle entries are minimal tool sequences
(`"click(btn-alpha)"`, `"scroll(down);key(down);key(down);key(enter)"`).
Actual = count of non-error tool steps in `run_steps`. `eff_obj =
min(1.0, oracle_len/max(actual_len,1))` — capped so a run can't score
>1 by being shorter than the oracle (shorter usually means skipped
setup). Record carries both `judge.efficiency` (as judged) and
`efficiency` (resolved: oracle if present else judge).

**Test scenarios:**
- Oracle `["click(a)"]` + 1-step run → eff 1.0; + 3-step run → 0.33.
- No oracle on the task → resolved efficiency falls back to judge value.
- Verified-fail run still records actual_len honestly.
- Suites without oracle fields parse unchanged (backward compat).

### U2. First-fault attribution in judge verdicts

**Goal:** every verdict names the earliest wrong/wasteful step.

**Requirements:** R2

**Files:**
- `wisp/judge.py` — schema + prompt addition
- `scripts/clicklab/run.py` — record `first_fault` on the run
- `scripts/clicklab/arena.html` — feed row shows the step index
- `tests/test_judge.py`

**Approach:** Judge questions gain `first_fault` ("earliest 0-indexed
step that was wrong, wasteful, or unnecessary — -1 if none") +
`fault_reason` (short phrase). Verdict dict gains both. On non-judge
runs (`--no-judge`) fall back: verified-fail → index of last non-error
step; verified-pass → -1.

**Test scenarios:**
- Judge answers step index 2 + reason → verdict carries both.
- `--no-judge` verified-fail → first_fault = last step index.
- Judge returns -1 → no fault recorded as such (not an error).
- Out-of-range index (≥len(steps)) → clamped to len-1 or -1.

### U3. Pass^k aggregation in stats

**Goal:** reliability over repeats, not pass@1 luck.

**Requirements:** R3

**Files:**
- `wisp/train.py` — `stats()` gains `reliability` section
- `scripts/clicklab/arena.html` — per-task pass^k in stats or bank card
- `tests/test_train.py`

**Approach:** Group results by `(surface|task|model)`. `runs`, `pass`
(≥1 verified), `pass_rate` = verified/runs. Pass^k display: for tasks
with ≥3 runs show `k:pass` — e.g. `3/3` all-green vs `1/3` flaky.
Simple fraction; no combinatorial estimator needed at our volumes.

**Test scenarios:**
- 3 runs same task/model, 2 verified → pass_rate 0.67.
- Different models → separate buckets.
- Mixed surfaces → separate buckets.
- Empty results → empty reliability section, no crash.

### U4. Flake taxonomy on run records

**Goal:** separate signal failures from environmental noise.

**Requirements:** R4

**Files:**
- `wisp/train.py` or `wisp/judge.py` — `classify_flake(rec)` pure fn
- `scripts/clicklab/run.py` — record `flake` field
- `scripts/clicklab/arena.html` — flake chips + histogram section
- `tests/test_train.py`

**Approach:** `classify_flake(rec) -> str` per KTD4 heuristics, applied
at record time. Arena stats gains `flakes` histogram; FAIL rows carry a
flake chip (`env`/`timing`/`model`).

**Test scenarios:**
- All steps ERROR infra-ish (mcp/BrowserOS/page) → `env`.
- verified=True + judge.success=False → `judge_fn`.
- verified=False + ≤2 steps + stall/timeout verdict → `timing`.
- Plain wrong-click fail → `model`.
- Verified pass without judge dissent → `none`.

### U5. Reviewer batch pass → staged proposals

**Goal:** async offline review converts failures into human-gated
skill candidates.

**Requirements:** R5

**Files:**
- `wisp/review.py` — new: batch over clicklab/trajectories records,
  decider-provider call, proposals writer
- `wispd` — `review` subcommand (list/run/approve)
- `tests/test_review.py`

**Approach:** `review.run(limit=N)` loads recent records with
`verified=False` or `flake="model"` or `efficiency<0.67`, bundles each
task+steps+verdict into a review prompt to the configured provider
(`[brain.reviewer]` section, falling back to brain default), and appends
structured proposals to `~/.local/share/wisp/review_proposals.jsonl`:
`{ts, task, model, first_fault, counterfactual: [steps], skill:
{name,when,steps}, confidence}`. `wispd review` lists proposals;
`wispd review approve N` copies `counterfactual`/`skill` into a bank
entry as `candidate` (never `graduated` — it must still earn its
streak). No automatic application of reviewer output anywhere — per
the Cheap Verifiers warning in the research doc.

**Test scenarios:**
- One failed record → one proposal with counterfactual steps parsed
  from a stubbed reviewer reply.
- approve copies skill to bank as `candidate`, not `graduated`.
- Reviewer unreachable → proposals skipped with a clear message, not
  a crash.
- Malformed reviewer JSON → record skipped, others still processed.
- `wispd review` with no proposals → friendly "nothing staged" output.

## Risks & Dependencies

- **Oracle drift:** authored oracles rot as the lab evolves — suites
  without oracles keep Jev-scored efficiency, so stale oracles are a
  gap not a wrong answer; flag oracle-vs-judge disagreement in the
  record (cheap judge-audit signal).
- **Reviewer cost:** batch pass on decider-class model is bounded by
  `limit` and runs only on failures/inefficient runs — default small.
- **Prompt contamination:** proposals never auto-apply — a wrong
  reviewer suggestion can only become `candidate` after human approval
  and still must earn graduation.

## Deferred Implementation Notes

- Exact flake heuristics thresholds (timeout words, step-count bound)
  — tune against live failure records during U4.
- Whether Pass^k wants a proper combinatorial estimator at higher
  volumes — plain fraction suffices now.
- Reviewer prompt format/schema — settle against the first real
  decider-provider replies; tests stub the provider.

## Scope Boundaries

Deferred: desktop-surface arena, Ember GUI implementation, weight-level
fine-tuning, auto-distillation of reviewer output into the actor prompt
(explicitly forbidden by origin research).
