---
plan: dim-u4-spoken-answers
created: 2026-09-27
status: ready
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U4
issue: https://github.com/duketopceo/wisp/issues/8
wave: 2
---

# U4 — Spoken answers (TTS) + barge-in

## Scope

`speak()` exists behind config. Make answer routes speak by default and
let a new `listen` kill in-flight speech.

## Steps

1. **Default on**: answer route calls `speak(reply)` when
   `voice_out=true` (already wired in both cores — verify paths).
2. **Barge-in**: track the espeak child pid in daemon state; an incoming
   `listen` command terminates it before recording starts. Same for
   the Python daemon — extract a `SpeakCtl` (pid + kill) shared by both
   pipeline and IPC handler.
3. **Per-OS voice**: Linux `espeak-ng`/`espeak` now; `say` (macOS) and
   SAPI (Windows) land inside U7/U8 adapters — the `speak` seam is
   already the boundary.
4. **Voice quality option**: config `voice_out_cmd` override so users
   can point at piper/better TTS without code changes.

## Tests

- Barge-in: fake speak proc (sleep), `listen` arrives, proc dead.
- `voice_out=false` → no spawn.
- `voice_out_cmd` override honored.

## Risks

- espeak latency makes barge-in feel laggy — keep the kill path fast
  (SIGTERM, not drain).

## Done when

An answer speaks aloud on <host>, and tapping the hotkey mid-speech
cuts it instantly.
