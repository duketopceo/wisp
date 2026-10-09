---
title: Voice answers — resolve pending prompts and interrupt by speaking
type: feat
date: 2026-10-08
status: done
---

# Voice answers — resolve pending prompts and interrupt by speaking

## Context

Verified break in "holding a conversation" (`wispd` record path +
`cancel.PromptBroker`):

- While a turn waits on `awaiting_choice` (clarify options or a confirm
  card), the turn thread is parked inside `PromptBroker.waiter` holding
  `ctl["busy"]`. A talk-key press hits `if ctl["busy"].is_set(): error
  "busy"` — **the mic can't even open**. The card can only be answered
  by clicking a chip or `wispd choice`; spoken "yes / the second one"
  does nothing.
- While a turn is `deciding`/`acting`, a press is likewise refused, so
  "stop" / "wait" by voice is impossible — the user must reach for Esc
  or middle-click.

Meanwhile the continuity machinery is already good: session tail (8
turns) feeds every turn's context, `goals.join_or_new` merges
continuations, `ASK_USER` questions are logged as `wisp: asked:` and
keep the goal open, the trigger screenshot is speculative. The missing
piece is strictly the busy-wall: a press during a parked/running turn
should capture a short *voice interjection* instead of being refused.

## Design

A **mini-capture** path in `wispd`, parallel to `_run_listen`:

- **Press while `busy` is set**: allowed (no new turn, no
  `begin_turn`, no `speech.stop()`, no token churn — the running turn
  owns all of that). Tagged `ctl["mini"] = "choice"` when a broker
  prompt is pending, else `"stop"`. If neither applies, keep refusing
  with `busy`. Recorder starts on a plain event, not the turn state —
  the parked turn's `awaiting_choice` status and card stay up (the
  resolution is the visual ack).
- **Release of a mini-capture**: transcribe the wav with the normal
  engine (`platform.transcribe`), then:
  - `"choice"`: `voicepick.map_pick(text, pending_options)` →
    `broker.offer(pick=…|index=…)`. Mapped → the parked turn resumes
    normally (confirm allow/deny, clarify pick). Unmapped → trace
    `choice_voice_unmapped`, leave the prompt pending, `notify`
    "didn't catch that" so the miss is audible feedback, not silence.
  - `"stop"`: stop-word match → `ctl["interrupt"].set()` +
    `token.cancel()`; the running turn unwinds via the normal
    INTERRUPTED path. Non-match → trace only, turn untouched.
- State surface: the mini-capture does not transition turn status —
  `awaiting_choice` keeps its card, `acting` keeps its steps. The
  bar pill reads status only, so it keeps showing "your call"/"working"
  (correct).

## Units

### U1. `wisp/voicepick.py` — pure utterance→pick mapper

`map_pick(text, options) -> int | None` (0-based option index):

- Ordinals/numbers: "the second one", "two", "2", "first" → `index`.
- Affirm/negate for confirm-style options (allow/deny wording):
  "yes/yeah/sure/do it/go ahead/allow" → the allow side;
  "no/nope/cancel/deny/don't" → the deny side. Match against the
  option labels' own words first (a card whose options are named
  "allow"/"deny" maps trivially; "open it"/"pick the file" style
  options use substring).
- Substring/word-overlap on option labels ("chrome" picks
  `app:firefox`… only if it appears — none → unmapped).
- Pure + exhaustive unit tests; no I/O.

### U2. Broker pending accessor + mini-capture in `wispd`

- `PromptBroker.pending()` → `{id, options}` or `None` (public view;
  `pending_id` exists but not the options).
- `wispd` press path: before the `busy` refusal, check
  `broker.pending_id` → set `ctl["mini"]="choice"`, start recorder,
  return `{"ok": True, "mini": "choice"}`. Release path: `ctl.pop("mini")`
  → transcribe → map → `broker.offer`; trace `choice_voice`
  `{mapped, pick}`.
- `broker.offer` already validates pick/index vs offered options —
  reuse it; an unmapped utterance never reaches `offer`.
- Tests: broker pending accessor; `voicepick` table; a daemon-level
  test with fake transcribe + a parked waiter — "yes" resolves a
  confirm, "the second one" resolves a 3-option clarify, garbage leaves
  the prompt pending.

### U3. Spoken stop while a turn runs

- Same mini-capture plumbing, `mini="stop"`: allow press while `busy`
  with no pending prompt (status deciding/acting/speaking).
- Release → transcribe → `voicepick.is_stop(text)` ("stop", "cancel",
  "never mind", "wait", "hold on", "don't") → `ctl["interrupt"].set()`,
  `token.cancel()`. Anything else → trace `interjection_dropped`, no
  side effects.
- Tests: stop-words interrupt a running (stubbed) turn; non-stop text
  leaves it running.

### U4. Continuity verification scenario

- Harness scenario: ASK_USER turn → next utterance "yes do it" →
  resolves against `wisp: asked:` in the session tail and proceeds
  (no re-ask). If it already passes, the test is the artifact; if not,
  fix the smallest thing that makes it pass.

## Non-goals

- Queued interjections ("wait, also add X" consumed as the next turn's
  text) — noted stretch, not this phase.
- Suggestion-card voice answers (daemon-level, not broker) — separate
  mechanism, revisit after this lands.
- Wake-word / continuous listening — still push-to-talk.

## Verification

- `python -m unittest tests.test_voicepick` — 23 tests: mapper table
  (affirm/deny/ordinal/overlap/unmapped), daemon wiring (parked broker
  resolved by "yes"/"nope"/"the third one", unmapped speech leaves the
  prompt pending, spoken stop cancels the token, idle press unaffected,
  stt failure clean), continuity (ASK_USER turn lands as `wisp: asked:`
  in the next turn's Jev context).
- `tests.test_cancel` + `test_session` + `test_pipeline` +
  `test_components` — 123 green alongside.
- Landed fix while testing: `_spoken_result` now renders both
  `ASK_USER x` (act loop) and `ASK_USER: x` (answer route) — the colon
  form was leaking raw `ASK_USER:` into Jev's session tail.
- Mini-capture records on `pipeline.record_start()` with no turn state;
  the phantom (<0.4s) branch settles the recorder without touching the
  parked turn's id or status.
- Remaining manual check on this machine: confirm card → press+say
  "yes" → card resolves; acting turn → press+say "stop" → INTERRUPTED.
