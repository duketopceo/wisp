---
title: Drop Training Stack and Add End-to-End Eval - Plan
type: refactor
date: 2026-10-26
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Drop Training Stack and Add End-to-End Eval - Plan

## Goal Capsule

- **Objective:** The owner can see, with one command, how often Wisp gets a turn right first time on this machine, broken down by kind of turn, and whether that clears the v1.0 bar — and the repo no longer carries the training, arena and per-route soak machinery that measured something else.
- **Means:** Delete the training/eval stack (U1); replace the per-route soak report with an outcome eval over hand labels keyed by turn kind (U2).
- **Authority:** Phase 4 of `docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md` (R5, R8).
- **Execution profile:** U1 then U2, serial (they share `wisp/learn.py`, `wisp/config.py`, CLI goldens and `docs/CONFIG.md`). Full Python suite must pass after each.
- **Stop conditions:** Stop if a deletion changes act-loop, routing or spend-cap behavior (anything beyond removing a training hint), or if `rs/` or `tests/fixtures/ipc_commands.jsonl` would change.
- **Who finishes:** This run's PR.

---

## Product Contract

### Summary

Delete clicklab, the arena, CubeVM hammer, label distillation, recipe proposals, the batch lane, the route eval and the weekly learning loop. Add `wispd eval`: correct-first-time rate per turn kind from `labels.jsonl`, with an owner-set gate.

### Requirements

**Removal**

- R1. These are gone with their CLI groups, config, tests, goldens and docs: `scripts/clicklab/`, `scripts/propose_criteria.py`, `wisp/train.py`, `wisp/judge.py`, `wisp/review.py`, `wisp/evalroute.py`, `wisp/batch.py`, `wisp/cli/batchcmd.py`, the `train`/`review`/`recipes`/`eval route`/`batch`/`learn weekly` command groups, `trajectories.propose_recipes`, and `learn`'s weekly/approve/overrides half.
- R2. Kept: `wisp/ledger.py` (spend caps), `learn`'s label store and correction/retry helpers, `trajectories.record`/`context_for`, `action_stats`, the turn-replay harness, recipe skills already installed, and everything Jev-router-related (shadow decider, decision replay, route A/B) — those go in Phase 5.

**Eval**

- R3. `wispd eval` reports, from `labels.jsonl` joined to `decisions.jsonl`, for each turn kind and in total: labelled turns, correct first time, incorrect, corrected by retry, and the correct-first-time rate.
- R4. Turn kind comes from the decision's `result` prefix (e.g. `ANSWERED` → answer, `ACTED` → act, `LAUNCHED` → launch, `DICTATED` → dictate, agent spawns → agent, everything else → other), so it works under any router.
- R5. A turn's outcome is its latest label: `correct`, `incorrect`, or `corrected-by-retry` (counted as not right first time).
- R6. The gate is `[eval] gate_rate` (a fraction, unset by default) and `[eval] gate_min_turns` (default 50). `wispd eval` prints PASS/FAIL against them, or "gate not set" when `gate_rate` is unset; `--json` emits the same as an object; exit status is 0 regardless.
- R7. `wispd label report` (the old soak report) is replaced by `wispd eval`; `wispd label set …` is unchanged.

### Key Decisions

- **Delete the training/eval stack; keep one end-to-end eval.** Governs R1, R3–R7. (session-settled: user-directed — chosen over archiving it on a branch or keeping it.)
- **The pass rate is the owner's call.** The gate ships unset rather than with an invented number. Governs R6.

### Scope Boundaries

- Out: the Jev router, shadow decider, decision replay and route A/B (Phase 5).
- Out: scoring replayed fixtures in `wispd eval` — CI's turn-replay corpus already asserts every fixture's expectations.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Act loop loses only the training hint.** `act.py`'s `train.hint_for` call is removed; trajectory and action-stat hints stay.
- KTD2. **Eval lives in `wisp/learn.py` beside the label store**, replacing `soak_stats`; the CLI command is a new top-level `eval` group verb in the CLI registry (reusing the freed `eval` group name).
- KTD3. **`learn.record_correction` and the corrections file stay** if any kept path reads them (`correction_context`, recall indexing); otherwise they go with the weekly loop — decide from the code.

---

## Implementation Units

### U1. Delete the training/eval stack

- **Goal:** R1 done, R2 intact.
- **Requirements:** R1, R2; KTD1, KTD3.
- **Files:** the R1 paths; `wisp/act.py`, `wisp/learn.py`, `wisp/trajectories.py`, `wisp/stage_route.py` (only the `learn.apply_overrides` call in `build_questions` and any recipe/train hooks), `wisp/cli/__init__.py`, `wisp/cli/learning.py`, `wispd`, `wisp/config.py` (`[clicklab]`), `wisp/settings_schema.py` (`clicklab.*`), `shell-plugin/lib/settings_schema.js` (regenerate), `tests/harness/fakes.py` + `tests/harness/runner.py` (FakeBatch), `.github/workflows/test.yml` (propose_criteria py_compile), the tests and help goldens named in R1, `tests/golden/cli_transcripts.json`, `tests/golden/cli_help/wispd.txt`, `docs/CONFIG.md`, `README.md`, `INDEX.md`, `docs/ARCHITECTURE.md`, `docs/OPS.md`.
- **Approach:** delete whole files first, then follow import errors and the docs/CLI lint to each call site; remove only the training-specific lines.
- **Test scenarios:** Test expectation: none new — deleted tests covered only deleted code; every other test passes unchanged.
- **Verification:** full suite green; `grep -rn 'clicklab\|evalroute\|wisp.train\|wisp.judge\|wisp.review\|batchcmd' wisp wispd scripts tests .github` finds nothing live.

### U2. End-to-end eval

- **Goal:** R3–R7.
- **Requirements:** R3, R4, R5, R6, R7; KTD2.
- **Dependencies:** U1.
- **Files:** `wisp/learn.py`, `wisp/cli/` (where `label` lives, plus the new `eval` verb), `wispd` (if `label report` routes through the daemon), `wisp/config.py`, `wisp/settings_schema.py` + regenerated `shell-plugin/lib/settings_schema.js` if `[eval]` keys are schema fields, `docs/CONFIG.md`, `README.md`, `ROADMAP.md` (v1.0 gate line), `tests/test_learn.py` or a new `tests/test_eval.py`, CLI help goldens.
- **Approach:** a pure function over the two JSONL files returns the per-kind table; the CLI renders text or JSON; the gate reads `[eval]`.
- **Test scenarios:**
  - Labels on an `ANSWERED` and an `ACTED` turn report under answer and act with the right counts and rate.
  - A turn labelled `incorrect` then `corrected-by-retry` counts once, as corrected-by-retry (latest label wins), not as correct.
  - A label whose `ref` has no decision counts under `other`.
  - `gate_rate = 0.6`, 50+ turns at 70% → PASS; at 50% → FAIL; fewer than `gate_min_turns` → FAIL with "needs N more labelled turns".
  - `gate_rate` unset → "gate not set" and no PASS/FAIL.
  - `--json` returns the same numbers as an object.
  - No labels → a clear "no labels yet" message.
- **Verification:** suite green; `wispd eval` on the real `~/.local/share/wisp` files prints a table (read-only).

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Python suite | `python3 -m unittest discover -s tests` | U1, U2 |
| Generated settings | `python3 scripts/assets/gen_settings.py --check` | U1, U2 |
| Parity | `git diff --quiet origin/master -- rs tests/fixtures/ipc_commands.jsonl` | all |

---

## Definition of Done

- R1 paths are gone with no live references; R2 pieces still work.
- `wispd eval` reports per-kind first-time-correct rates and the gate state; tests cover R3–R7.
- Full suite green; parity untouched.
