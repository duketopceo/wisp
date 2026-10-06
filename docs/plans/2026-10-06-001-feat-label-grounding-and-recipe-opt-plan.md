---
title: Wisp label-grounding + recipe optimization wave
type: feat
date: 2026-10-06
status: active
---

# Next training wave — label grounding, recipe optimization, coverage

## Context

Corpus after PRs #106/#107 (CubeVM, gemma-4-31b-it):

| suite | verified | residual failure |
|---|---|---|
| dom-hard | 12/12 | — |
| apps-nodes | 3/4 | aim variance (n-blur-input vs n-blur-radius) |
| apps-chess/email/settings | 100% | — |
| apps-editor | ~50% | id-less elements untargetable — `open utils.py` types into search instead of clicking the file row; legend only exposes `id`, file rows have none |
| core | ~64% | mixed |

Skill bank: 140 entries — 22 graduated, 109 candidate, 9 demoted. Many
candidates carry streaks of 30–65 verified runs but sit below the 0.9
efficiency floor: they pass reliably, waste steps, never graduate, and
their sequences never reach `hint_for()` prompts.

## Units

### U1. Legend labels for id-less elements

`dom_els` entries are `id@(x,y)`; for elements with no id the id falls
back to the tag name (`div`, `button`) — non-unique and unhelpful. The
schematic already computes `label` (textContent/placeholder, 24 chars).

- In `_dom_slice`/`_dom_shot` (wisp/tools/system.py): when `el.id` is
  empty, emit `label@(x,y)` (escaped) instead of `tag@(x,y)` when the
  label is non-empty and unique-ish; keep `tag@` as last resort.
- `_CLICK_ID_JS` already matches `textContent===want` — verify label
  args dispatch, extend the fallback chain if partial-label matching is
  needed.
- Tests: legend for `<div data-file>utils.py</div>` carries the label;
  `click 'utils.py'` dispatches a hit; tag fallback preserved when no
  label.

Expected: `apps-editor` file-open tasks and label-aimed tasks in
`core`/`dom-hard` improve without model-side changes.

### U2. Candidate recipe optimization → graduation

Recipes pass reliably but wastefully never reach `hint_for()`. Add a
distill path in `wisp/train.py` + `scripts/clicklab/run.py`:

- `run.py --distill`: for each candidate with `streak>=3` and
  `eff<0.9`, take the recorded steps, drop `screenshot` calls whose
  result was `"(unchanged)"` or that followed a no-mutation step, drop
  `move`/probe steps not required for verification, then replay the
  minimal sequence on a fresh seed. Re-verified + step count <= oracle
  minimum × 1.1 → graduate with `recipe_id`.
- Record `optimized: true` + `orig_steps`/`opt_steps` on the entry so
  the report shows the savings.
- Tests: distillation removes redundant observes; graduation only after
  re-verify; `--distill --dry-run` lists without mutating the bank.

Expected: the streak-30+ candidates graduate → `hint_for()` injects
proven sequences into act prompts → live tasks skip the exploration
steps entirely.

### U3. Coverage refresh — full parallel hammer, new seeds

`hammer-parallel.sh 2` across every suite with seeds not in the corpus
(seed 11, 23), after U1+U2 land. Report deltas per suite vs the last
baseline; new failures get waste-classified into the next wave.

### U4. Daily-use readiness pass (user will start running it)

- `apps-editor` residual fixes from U1's live traces (search→open file
  flow, `ln-N` click → cursor-line oracle).
- `core` stragglers from the U3 corpus.
- Smoke the daemon path end-to-end locally (not just clicklab): one
  PTT invocation → act → verify on the real desktop.

## Non-goals

W12 (STT engine — still the user's open decision), W30/W31/W33/W34,
per-app recipe splitting, SFT export.

## Verification

- `tests/test_cube.py`, `tests/test_act.py`, `tests/test_train.py` green
- Live: dom-hard stays 12/12, apps-nodes >=3/4, apps-editor >=3/4 on
  seed 7 AND a fresh seed
- `report.py` shows fewer `unneeded_observe`/`extra_steps` vs baseline
