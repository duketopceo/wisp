---
title: Act loop reported success from a screenshot taken before its own last action
date: 2026-11-15
category: logic-errors
module: wisp/act.py
problem_type: logic_error
component: service_layer
symptoms:
  - "Gauntlet cases score 0/3 while every run reports ACTED with a confident one-line outcome"
  - "The judge says the folder was not created or the file was not renamed, but the agent said it was"
  - "A run reports \"ACTED (0 steps): done\" with no tool call at all"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags: [act-loop, gauntlet, verification, false-success, screenshot, trace]
---

# Act loop reported success from a screenshot taken before its own last action

## Problem
Four gauntlet cases (files-new-folder, files-rename, terminal-make-dir, browser-follow-contact) failed every repeat, yet each run reported success. They looked like weak skills or over-cautious guards; they were false successes. Nothing was refused.

## Symptoms
- Evidence JSON shows `outcome: success` and `result: ACTED (n steps): <confident sentence>`, and the check fails.
- In files-new-folder, the text the agent "typed into the new folder field" landed in the file manager's search box ("No Results Found").
- In browser-follow-contact, the click by name landed on the heading above the link; the page never changed.
- In files-rename, some runs ended "ACTED (0 steps): done" after one empty model reply.

## What Didn't Work
- Reading the judge's `reason` in the evidence JSON. Judges are inconsistent: one marked a rename "successfully renamed" when the check failed, another said "draft.txt not found" when it was there. Use them as hints only.
- Assuming a guard refused the step. None of the four runs hit a Wisp guard; the route guard for new folders (`act_guards.RunGuards.unverified_done`) passes when the new name appears anywhere in the window text, and the typed name was sitting in the search box.

## Solution
The diagnosis came from the gauntlet host's `trace.jsonl` (in the gauntlet data dir), filtered by the `turn` id from the case's evidence JSON. Each `llm_call` event records `img_kb`, the size of the image the model was shown. In every failed run it stayed the same from the first call to the done claim. The model never saw the screen after its own key presses, typing, or click. It even narrated a dialog that never opened ("the shortcut brought up a text entry field").

Two gaps in `run_act_loop` allowed it:
- The automatic re-observe only runs before a pointer step (`click`/`move`). `key` and `type_text` return `KEY`/`TYPED` whatever the screen does, so a run ending in keyboard steps, or in one click, reaches its done claim with no fresh look.
- A reply with neither text nor a tool call fell through to the done branch (`text or 'done'`).

The fix, on branch `fix/act-verify-done-claims`:
- A tool-less done claim, with vision on and the screen dirtied by a screen-changing step, triggers one fresh screenshot. It is attached with `_VERIFY_DONE_NUDGE`, so the model confirms or corrects before the claim stands. The shot is part of the check and is not appended to `steps`, so it never spends the step budget. Each new screen-changing step dirties the screen again, so a later claim is checked too.
- An empty reply is nudged once (`MAX_EMPTY_NUDGES`, `_EMPTY_NUDGE`) and then returns `STALLED (the model gave no answer)`.
- `STALLED` counts as a failure in `telemetry.digest`, trajectory memory (`outcome_failed`), and `session._spoken_result`. Before this, the older unparseable-reply `STALLED` was also scored as success.

## Why This Works
The prompt already told the model that a fresh screenshot after a mutating step is the verify pass, but nothing enforced it. Enforcing one look before "done" turns these silent false successes into either a corrected answer or another attempt. That matters for the owner's main complaint: when the agent says it did something, it must have.

## Prevention
- Diagnosing a gauntlet case: check the trace's `img_kb` sequence and the `reply` text on each `llm_call` before blaming guards or skills. A constant `img_kb` across steps means the model is working blind.
- A 0/3 case is not always the agent's fault. `terminal-make-dir` can never pass, because the gauntlet's sandbox shell (`scripts/gauntlet/rsh`) is a read-only allowlist that refuses `mkdir`. Check that the harness permits a case before tuning the agent for it.
- Tests: `tests/test_act.py` covers the verify shot after unobserved keys, the step budget at `max_steps - 1`, a second claim after more steps, and the empty-reply stall.

## Related Issues
- Gauntlet run `gauntlet-20261111-053547` (held-out 55%, tuning 76% after #380).
