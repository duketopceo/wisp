---
module: wisp/copy.py
date: 2026-11-27
problem_type: test_failure
component: tooling
severity: medium
symptoms:
  - "A settings Status page (Health, Spend) shows a raw copy key such as `state.stale` instead of words"
  - "`scripts/ui/snap.py check` passes both before and after the copy is fixed; the golden itself shows the raw key"
root_cause: missing_validation
resolution_type: test_fix
tags:
  - copy
  - copy-key
  - snapshot
  - golden
  - snap-py
  - tolerance
---

# Snapshot goldens do not catch a missing or wrong copy key

## Problem

A copy key was removed from `wisp/copy.py` `STRINGS` while two QML pages still
read it. Nothing failed: the pages showed the key text (`state.stale`) and the
snapshot goldens recorded that text as the expected render.

## Root cause

Two silent fallbacks stack:

1. Unknown keys render as themselves. `wisp/copy.py:611-613` (`string()`
   returns `STRINGS.get(key, key)`) and `shell-plugin/lib/copy.js:18`
   (`function string(key)` returns `key` when absent) both do this by design, so
   a typo stays visible instead of crashing a surface. The cost is that a
   missing key is never an error.
2. Snapshot tolerance absorbs a text change of the same length. `scripts/ui/snap.py`
   compares within a per-component tolerance (`DEFAULT_TOLERANCE` and the
   `TOLERANCE` table, e.g. `HealthSection`/`HealthView` at fraction 0.012).
   Replacing the 11-character `state.stale` with the 11-character
   `out of date` in a monospace font changed about 362 px of a 380x426
   render (1x), well under that fraction, so `snap.py check` passed against
   both the broken and the fixed render.

The key was deleted in the W25 copy rework (the commit titled "confirm card
and error/offline/stale UX from one copy table (W25)"); the stale Health and
Spend goldens were then generated with the raw key in them.

## Solution

- Restore the key in `wisp/copy.py` and regenerate `shell-plugin/lib/copy.js`
  with `python3 scripts/assets/gen_copy.py`.
- Guard key existence with a unit test, not a golden: `tests/test_copy.py`
  `TestKeysExist` scans `shell-plugin`, `shells` and `wisp` for literal
  `string("...")` / `ui("...")` reads and asserts each key is in `STRINGS`,
  with a separate check that each settings Status page reads at least one key.
- Regenerate only the affected goldens: `python3 scripts/ui/snap.py update --only stale`,
  then restore any golden the update rewrote that the change does not touch
  (in this fix, `Companion__stale` and `Composer__stale` were rewritten from
  in-tolerance render noise) with `git checkout HEAD -- <paths>`, and rerun
  `snap.py check`.

## Prevention

- Treat goldens as a layout guard, not a copy guard. When a change touches
  copy keys, look at the affected golden PNGs; do not rely on `check` passing.
- When removing a key from `STRINGS`, search every reader first:
  `rg -n '"<key>"' shell-plugin shells wisp`.
- Known limit of the scan: it reads only a single literal argument. Keys
  picked by a ternary (`ui(cond ? "ui.a" : "ui.b")`), built from a prefix
  (`"ui.cua." + state`), or read through a wrapper such as `_ui(...)` in
  `wisp/tui.py` are not checked by it.
