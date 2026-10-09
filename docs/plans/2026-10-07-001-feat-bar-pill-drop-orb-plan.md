---
title: Wisp bar-pill live activity — drop the corner orb
type: feat
date: 2026-10-07
status: active
---

# Bar-pill live activity — drop the corner orb

## Context

The wisp plugin renders two layer windows (Companion.qml, Ember U11-U13):

- `wisp-companion` — persistent corner creature + console, bottom-right.
  Sits over content permanently; user hit it blocking a button and asked
  for it gone: *"drop the orb for a top bar drop down on the icon that
  was there — top bar center, like a macbook live activities thing"*.
- `wisp-points` — transient overlay (listening pill, answer bubble,
  ghost cursor, beacons). Only shows during a turn; that IS the product
  value. **Keep.**

The bar surface already exists: `BarWidget.qml` (glyph + clicks:
left=talk, middle=stop, right=Panel) and `Panel.qml` (4-tab dropdown:
Now/Agents/Memory/Settings). Missing: the bar mark is a static glyph —
no live-activities presence while busy.

## Units

### U1. Remove the corner creature window

- Companion.qml: drop the `wisp-companion` PanelWindow block,
  `capTimer`, `hidden`/`userOpen` console state, `consoleExtent` and the
  `onCornerClicked/onHide/onTalk` handlers that only serve the corner.
- Keep the `wisp-points` overlay window and its Process/Timer wiring.
- Delete dead components: `CornerLayer.qml`, `Corner.qml`, `Console.qml`
  (sole consumer was the corner window — verified by grep).
- OverlayLayer: drop `consoleExtent` prop + the console-avoidance term
  in bubble x placement (console no longer exists → 0).
- lib/companion.js: prune corner/console helpers if orphaned by the
  same grep.

### U2. Live-activities bar pill

- `components/BarPill.qml` (new): compact in-bar pill —
  Mark + status word (wordView word/tone) + transcript tail when
  listening. Shown while `service.busy` or a choice/suggestion is
  pending; hidden at idle so the bar stays clean.
- BarWidget.qml: host BarPill inside the same WidgetButton so existing
  click semantics survive (left=talk toggle, middle=stop, right=Panel).
  `fixedWidth`/implicitWidth grows with the pill; width animate on
  show/hide for the live-activities feel.
- Keep BarMark's badge/ring semantics — they fold into the pill.

### U3. Deploy + visual verify

- Sync repo `shell-plugin/` → `~/.config/omarchy/plugins/io.github.duketopceo.wisp/`
  (rsync the source set; deployed copy is stale by ~16h anyway).
- `omarchy-plugin-enable io.github.duketopceo.wisp`, confirm:
  `hyprctl layers` has `wisp-points` only (no `wisp-companion`);
  bar shows the glyph; screenshot the bar with wispd idle vs forced
  busy state if a turn can be triggered cheaply.

## Non-goals

- Panel tab redesign — existing 4-tab panel stays.
- Debug shell (`shells/debug`) changes.
- wispd/daemon changes — this wave is shell-plugin only.

## Verification

- `grep` CornerLayer/Corner/Console → zero references outside deleted files.
- QML syntax: `qmlfmt`/`qmllint` if available, else careful review.
- `hyprctl layers` post-enable: wisp-companion absent, wisp-points
  present but hidden at idle.
- Screenshot the bar idle + busy.
