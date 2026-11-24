---
module: tests/qml/harness
date: 2026-11-23
problem_type: test_failure
component: tooling
severity: medium
symptoms:
  - "A Column-based component's snapshot golden renders as a thin strip (for example 380x28) holding only its first row"
  - "`scripts/ui/snap.py check` reports size diffs such as `size (380, 746) vs (380, 28)` right after a component's default width is removed"
  - "The same component renders correctly when another component mounts it and sets its width"
root_cause: incomplete_setup
resolution_type: code_fix
tags:
  - qml
  - snapshot
  - golden
  - snap-py
  - scenes-json
  - column-layout
  - default-width
---

# Snapshot golden collapses when a component has no default width

## Problem

The offscreen snapshot harness (`tests/qml/harness/Snap.qml`, driven by
`scripts/ui/snap.py`) renders a window-free component from
`tests/qml/harness/scenes.json`. A component whose root is a `Column` and that
declares no `width` of its own renders as a collapsed strip, even though the
scene sets a `width`. The golden then shows only the first child.

## Symptoms

- In one-surface U2, removing `width: 340` from `shell-plugin/components/DevTab.qml`
  turned the 14 DevTab goldens from full height (for example 380x746) into 380x28 (`snap.py check`:
  `DIFF light/1x/DevTab__runs: size (380, 746) vs (380, 28)`).
- The new `QuickTab.qml` had no default width at first. Its six standalone
  scenes (18 goldens) showed only the health row, while the same tab inside the
  `PanelBody` scenes rendered in full.

## What Didn't Work

- Treating the scene-level `"width"` in `scenes.json` as the component's width.
  The harness applies it only after the object exists (see below). So the
  scene `DevTab: {"width": 360}` did not keep DevTab from collapsing once its
  own default was gone.

## Solution

Give every window-free component that the harness renders on its own a
default `width`, and let hosts override it:

```qml
// shell-plugin/components/QuickTab.qml
// the Panel sets the page width; this default only seeds a first layout
width: 456
```

`DevTab.qml` keeps its `width: 340` for the same reason. In the Panel,
`PanelBody.qml` binds both tabs to the page width, so the default never shows
there.

Alternatively, a scene can pass the size per variant. Variant keys are
component properties and go into `createObject` as initial properties. The
`PanelBody` scenes do this (`"width": 480, "height": 560` in each variant), so
the size is right from the first layout (`PanelBody.qml` also keeps its own
`width: 480` default).

## Why This Works

`Snap.qml` creates the item first and assigns the scene size afterwards:

- `tests/qml/harness/Snap.qml:75`: `var item = comp.createObject(host, props);`
  where `props` holds the variant's keys.
- `tests/qml/harness/Snap.qml:80`: `if (c.width) item.width = c.width;`, where
  `c.width` comes from the scene level (`scripts/ui/snap.py:175`).

The item therefore exists, and lays out its first pass, at width 0. In this
session a component that laid out at width 0 first kept the collapsed height in
its golden (a code-only reading suggests the grab happens before the `Column`
re-polishes at the new width; the exact timing was not measured). A default
width, or a width passed in `props`, makes the first layout correct.

## Prevention

- Do not remove a "magic" default `width` from a component under
  `shell-plugin/components/` just because its host overrides it. Check first
  whether `scenes.json` renders that component on its own. If the plan asks
  for the width to go, set the size per variant in its scenes instead.
- A new component that `scenes.json` renders on its own needs either a
  default `width` or per-variant `"width"`/`"height"` keys.
- After any change to a component's size properties, run
  `python3 scripts/ui/snap.py check` before `update`. A size diff like
  `(w, H) vs (w, 28)` is this failure, not a real redesign, so do not accept
  it with `update`.
- Related, in `qmltestrunner` tests: `Column` positions children at polish
  time, so after toggling child visibility call `waitForRendering(item)` before
  reading `implicitHeight` or clicking a child (`tests/qml/lib/tst_panel.qml`,
  `show()`).
