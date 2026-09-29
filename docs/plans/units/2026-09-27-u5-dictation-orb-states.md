---
plan: dim-u5-dictation-orb-states
created: 2026-09-27
status: ready
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U5
issue: https://github.com/duketopceo/wisp/issues/9
wave: 2
---

# U5 — Dictation route + richer orb states

## Scope

`route=dictation` types the transcript at the cursor; the orb shows
speaking/pointing states.

## Steps

1. **Dictation route**: Jev `route` question already emits dictation as
   a choice — add the execute branch: transcript → `type_text`
   (mutating tier → existing confirm gate applies). Both cores.
2. **Trigger ergonomics**: "dictate"/"type this" phrasing lands on the
   dictation route via Jev criteria text; verify with a live Jev call.
3. **Orb states** (`Companion.qml`): `speaking` (pulsing during TTS),
   waveform driven by `state.json.level`, pointer badge when
   `points` non-empty.

## Tests

- Dictation executes `type_text` with the transcript, goes through the
  mutating-tier gate.
- `points`/`level` state fields drive orb visuals (QML unit-visible
  bindings; manual smoke).

## Risks

- `wtype` into Wayland chromium/electron is the known-flaky path —
  dictation quality gate is per-app; document fallbacks (clipboard
  paste) if misses are common.

## Done when

"Dictate" types the transcript into the focused app on <host>.
