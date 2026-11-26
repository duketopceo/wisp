---
title: Replay and scenario tests fail locally when a person uses the desktop during the run
date: 2026-11-25
category: test-failures
module: tests/test_replay.py, tests/test_scenarios.py
problem_type: test_failure
component: tooling
symptoms:
  - "tests/test_replay.py fails with result_prefix 'ACTED' not in 'INTERRUPTED (user)'"
  - "tests/test_scenarios.py status sequences end in 'idle' where 'speaking' then 'done' are expected"
  - "IndexError on res.chat_calls()[1] in test_refusal_is_scriptable"
  - "The same failures reproduce on an untouched origin/master worktree"
root_cause: test_isolation
resolution_type: workflow_improvement
severity: medium
retire_when: "The replay and scenario harness stubs realinput (yielded() returns False or the global watch is stopped) for every replayed turn; check tests/test_replay.py and tests/test_scenarios.py setup for realinput"
tags: [replay-harness, realinput, act-loop, flaky-local, environmental, unittest]
---

# Replay and scenario tests fail locally when a person uses the desktop during the run

## Problem

The replay and scenario tests drive the real act pipeline against fakes. Run
locally, they fail whenever a person uses the machine's keyboard or mouse
during the run. The failures look like logic regressions in whatever branch is
checked out, but the cause is the machine, not the code. CI runs headless, so
it is expected to be unaffected: no person is at its input devices.

## Symptoms

- `result_prefix 'ACTED' not in 'INTERRUPTED (user)'` from `tests/test_replay.py`
  (several fixtures, for example `act_click_cua.json`, `act_confirm_yes.json`,
  `cua_rate_limited.json`).
- Scenario status sequences end in `idle` instead of `speaking`, `done`
  (`tests/test_scenarios.py`).
- `IndexError` on `res.chat_calls()[1]` in `test_refusal_is_scriptable`
  (`tests/test_replay.py`): the turn aborts before the brain's second chat
  call, so that call never exists.
- In the session that found this, an earlier full run of
  `python3 -m unittest discover -s tests` on the same branch, during an idle
  stretch, passed (5414 tests OK).

## What Didn't Work

- Blaming the branch diff. The branch that hit this (one-surface U7) touched
  only shell-plugin QML and JS, the QML test harness and snapshots,
  `tests/test_components.py`, copy keys and docs, nothing in `wisp/act.py`,
  `wisp/realinput.py` or the replay tests. In this session the same tests
  also failed in an untouched `origin/master` worktree.
- Running two `unittest discover` processes at once in the same checkout. The
  overlap added noise and made the failures harder to read; it did not explain
  them.

## Solution

No code change was made. The workflow that tells the two cases apart:

1. Rerun the failing module alone with hands off the keyboard and mouse, for
   example `python3 -m unittest discover -s tests -p test_replay.py`.
2. If it still fails, run the same module in an untouched `origin/master`
   worktree before debugging the branch. A failure there only shows the
   cause is not unique to the branch; it could still be a defect already on
   `master`. Call it environmental only when the interruption evidence is
   there too: the turn ends `INTERRUPTED (user)` and the failure goes away
   in a hands-off run.
3. Run one test process per checkout at a time.

## Why This Works

The act loop checks for a user takeover through `stopped()`, which returns
`cancel.is_cancelled() or _user_interrupted()` (`wisp/act.py`, `stopped`), and
`_user_interrupted()` is `bool(interrupted and interrupted()) or
realinput.yielded()`. Act paths that see a stop return the string
`"INTERRUPTED (user)"`.

`realinput.yielded()` reports the global input watch's yield flag, and the
watch is armed for any run that injects input (`_watch_wanted` in
`wisp/realinput.py`: drive or auto pointer mode, not an isolated session, not a
DOM-page run). The watch senses the real input devices, so a person's
keystroke or mouse motion during a replayed turn sets the flag and the turn
aborts. That one cause explains the wrong result prefix, the missing second
chat call, and the scenario statuses ending in `idle`. A headless CI runner has
no person at the devices, so the flag never sets there.

Which fixtures arm the watch was inferred from the symptoms and the code
above, not traced fixture by fixture. The idle-run pass and the reproduction on
`origin/master` are the empirical support.

## Prevention

- Before debugging a local replay or scenario failure, ask whether anyone was
  using the desktop, and compare against an untouched `origin/master` worktree.
- Suggested, not done: have the replay and scenario harness keep the watch
  out of every replayed turn, for example by stubbing `realinput.yielded()`
  to return False for the whole run. A one-time `realinput._stop_for_test()`
  in setup is not enough on its own: `realinput.begin(cfg)` creates a fresh
  watch at the start of each act run whenever drive or auto pointer mode
  wants one, so the stop is undone by the next turn.
- Do not run overlapping `unittest discover` processes in one checkout.
