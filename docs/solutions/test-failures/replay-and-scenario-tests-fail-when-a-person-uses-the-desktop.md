---
title: Replay and scenario tests fail locally when a person uses the desktop during the run
date: 2026-11-25
last_updated: 2026-11-27
category: test-failures
module: tests/harness/_child.py, tests/test_replay.py, tests/test_scenarios.py
problem_type: test_failure
component: tooling
symptoms:
  - "tests/test_replay.py fails with result_prefix 'ACTED' not in 'INTERRUPTED (user)'"
  - "tests/test_scenarios.py status sequences end in 'idle' where 'speaking' then 'done' are expected"
  - "IndexError on res.chat_calls()[1] in test_refusal_is_scriptable"
  - "The same failures reproduce on an untouched origin/master worktree"
root_cause: test_isolation
resolution_type: test_fix
severity: medium
tags: [replay-harness, realinput, act-loop, flaky-local, hermetic-tests, hyprland, unittest]
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
- Stubbing `realinput.yielded()` or calling `realinput._stop_for_test()` once
  in setup (the earlier suggestion). `realinput._watch()` builds the
  process-wide watch through `_create()` whenever `_WATCH` is `None`
  (`wisp/realinput.py:291-302`), and `begin(cfg)` calls `_watch()` for
  every drive or auto run. `_stop_for_test()` only clears `_WATCH`, so the
  next such `begin()` builds a live watch from the real devices again. A
  `yielded()` stub would also hide a regression instead of reporting it. The
  seam has to replace `_create`.
- Patching from the test process. The replay turn runs in a separate child
  process, so a patch applied in the parent never reaches it. The seam has to
  live in the child entry point.

## Solution

The fix is test-side only; production `wisp/` is unchanged. It ships in the
same pull request as this revision of the doc, from branch
`fix/replay-desktop-input`.

`hermetic_realinput(violations)` in `tests/harness/_child.py` rewires
`wisp.realinput` inside the replay child:

- It calls `realinput._stop_for_test()` and replaces `realinput._create` with a
  factory that returns `realinput.Watch(devices=[], cursor_pos=lambda: None)`.
  That watch is never started, so its mode stays `"off"`, as on a headless CI
  runner.
- It replaces `realinput.real_devices` and `realinput._hypr_cursor_pos` with
  functions that append `"host input: ..."` to the `violations` list and
  return empty values.

`main()` calls it inside its `try`, right after the `wisp` import, with a
`host_reads` list, and the `finally` block writes
`list(guard.violations) + host_reads` to `out["violations"]`. Any replay turn
that reaches the host's input therefore fails the tests that assert
`res.violations == []`.

Tests, in `HostInputTest` in `tests/test_replay.py`:

- `test_replay_ignores_host_input` is the discriminating one. It patches
  `real_devices` to return a pipe and `_hypr_cursor_pos` to return an
  ever-moving cursor, applies the seam, calls
  `begin({"pointer": {"mode": "drive"}})` and `arm()`, writes bytes to the
  pipe, and asserts `yielded()` is False, `check()` does not raise, and no
  violations were recorded. Without the seam, the same setup selects evdev
  mode and `yielded()` becomes True after the writes (demonstrated this
  session).
- `test_seam_flags_any_host_input_read` asserts that calling either replaced
  function records a violation.
- `test_drive_fixture_turn_reads_no_host_input` runs `act_click_cua` (a
  drive-mode fixture) through `runner.run_turn` and asserts no violations and
  a result starting with `ACTED`.

## Why This Works

The act loop checks for a takeover through `stopped()`, which returns
`cancel.is_cancelled() or _user_interrupted()` (`wisp/act.py:360-361`).
`_user_interrupted()` is `bool(interrupted and interrupted()) or
realinput.yielded()` (`wisp/act.py:356-358`), and `yielded()` reads the
process-wide watch (`wisp/realinput.py:360-362`). Act paths that see a stop
return `"INTERRUPTED (user)"`.

`realinput.begin(cfg)` gets that watch from `_watch()`, which builds it
with `_create()` the first time, for any run where `_watch_wanted` is true (drive or auto pointer mode, not
isolated, not a DOM-page run; `wisp/realinput.py:310-319`), then arms it after
`BACKGROUND_GRACE_S` (1.0 s) via `arm_background` (`wisp/realinput.py:322-336`).
`Watch.start` uses the evdev devices from `real_devices()` when it finds any.
When none are readable it falls back to drift mode if `_hypr_cursor_pos()`
returns a position, and to `"off"` otherwise (`wisp/realinput.py:114-134`).

On the owner's machine, measured in this session, `real_devices()` returned
no fds and `_hypr_cursor_pos()` was readable. The live watch therefore runs in
drift mode, so mouse motion alone trips the takeover. Keystrokes were not
needed to reproduce.

The seam removes the cause rather than hiding the symptom. The watch built for
every replayed turn has no devices and no cursor reader, so it stays `"off"`
and `yielded()` is False no matter what the host does. Because the real
sources are replaced by violation recorders, a future code path that reaches
the host's input anew fails loudly instead of flaking only on a desk where
someone is working.

## Prevention

- Keep the replay child hermetic. When `wisp/realinput.py` gains a new way to
  sense the host (another device source, another cursor reader), route it
  through the seam in `hermetic_realinput` so it records a violation.
- Tests that assert `res.violations == []` now also cover host-input reads;
  do not drop `host_reads` from the `finally` in `tests/harness/_child.py`.
- Known residual, not fixed here: in-process drive-mode act tests such as
  `run_loop` in `tests/test_ground_chain.py` (around line 599) still build a
  live watch from the host cursor. They are shielded only by the 1 s arm
  grace, so a slow test or a long-running one could still be hit. If one
  flakes with `INTERRUPTED (user)`, apply the same `_create` replacement there.
- Before debugging a local replay or scenario failure that ends in
  `INTERRUPTED (user)`, ask whether anyone was using the desktop, and compare
  against an untouched `origin/master` worktree.
- Do not run overlapping `unittest discover` processes in one checkout.
