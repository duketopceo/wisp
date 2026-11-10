---
plan: dim-u3-cursor-pointing-overlay
created: 2026-09-27
status: ready
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U3
issue: https://github.com/duketopceo/wisp/issues/7
wave: 2
---

# U3 — Cursor pointing overlay

## Scope

Wisp answers "where do I click" by *showing*, not telling. Parse
`[POINT:x,y:label]` / `[POINTS:[...]]` tags from model output and render
an animated pointer on a layer-shell overlay.

## Steps

1. **Spike (first hour)**: layer-shell overlay can be click-through AND
   receive a dismiss event — test `layer-shell` overlay layer with
   `keyboard: none` + a hotkey-driven dismiss as fallback.
2. **Tag grammar**: pipeline extracts `[POINT:...]` blocks from answer/
   agent replies, strips them from displayed text, publishes
   `points: [{x,y,label}]` (screenshot pixel coords) in `state.json`.
3. **Coordinate normalization**: screenshot px → logical coords via
   `hyprctl monitors -j` scale per output (eDP-1 = 2, DP-3 = 1). Pure
   function + unit tests with scale fixtures.
4. **`Pointer.qml`**: overlay layer surface; cursor glyph animates to
   each point (sequential for `[POINTS]`), label chip beside it,
   auto-hide ~8s after last point.
5. **Prompt**: answer system prompt documents the tag grammar when
   `needs_screen` fired.

## Tests

- Parser: tags extracted, stripped from user-visible text, malformed
  tags tolerated.
- Coord map: scale-2 and scale-1 fixtures, multi-monitor offsets.
- Contract: `points` field added to `docs/IPC_CONTRACT.md` schema.

## Risks

- Model coordinate accuracy on downscaled screenshots — cap screenshot
  resolution if misses are systematic.
- Overlays on other shells (Wave 4) get their own renderer.

## Done when

"Wisp, where do I click to mute" produces a visible pointer at the right
control on the owner's machine.
