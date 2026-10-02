# feat: Wisp conversational agent — Talk/Agent modes, goals, screen-first

Date: 2026-10-02 (revised after Hey Clicky research)
Status: planned
Source: live dogfood session 2026-10-02 (Robinhood/GDX sequence) +
Clicky architecture teardown (isaacflath.com/writing/how-clicky-works,
farzaa/clicky repo, jasonkneen/openclicky README)

## Problem

The Robinhood sequence shows Wisp is a slot-filler, not an agent:

```
"check my robinhood account"      → "not a recognized application"
"open it up in a browser"         → tried chromium (wrong browser)
"just do command t for a new tab" → "shell command was declined"
"type in robinhood.com"           → "I cannot proceed without a click"
"click on gdx"                    → clicked wrong coordinates
"nope, you didn't"                → apologized, corrected
```

Five separate acts, zero shared goal. Each turn restarted from scratch —
Wisp never knew it was still trying to get to GDX.

## What Hey Clicky does (the workflow to match)

1. **Two modes.** Talk = hotkey → screen+voice → spoken answer + point.
   Agent = "heyclicky agent …" → computer-use loop. The screen is
   captured *at hotkey press*, before the model runs — it never asks
   "what app" because it already sees the app.
2. **Route order is structured-first.** (OpenClicky fork, explicit in
   its prompt): direct answer → web search → spawn agent → computer
   use as last-mile fallback only. GUI automation is the tail, not the
   head.
3. **Parallel capture.** STT + screenshot + per-app memory tail + KB
   lookup all kick off at hotkey release, then one model call gets
   everything.
4. **Points annotate, not execute.** `[POINT:x,y:label]` after spoken
   text — the same primitive we already ship. Clicky's cursor trails
   with spring physics and arcs to targets; our ring+ghost does this.
5. **Conversation = last 10 turns**, plus per-app markdown memory.

## Design deltas vs the earlier draft

The draft said "screenshot is step 0 of the act loop". Clicky shows the
better order: **screenshot at trigger** — the screen rides into the
Jev decision itself, so routing is screen-aware instead of
transcript-only. `needs_screen` becomes a yes/no the pipeline handles
before asking Jev, not a flag Jev computes blind.

And modes are explicit: Talk is the default (screen + answer + point —
most utterances end here), Agent is the multi-step worker. The current
`act` route conflates "point at it" and "do it" — that ambiguity is
why "click on gdx" produced one blind click instead of a workflow.

## Units

| # | Unit | What changes |
|---|------|--------------|
| U1 | Screen-first trigger | `run_turn` captures screenshot + attaches it to the Jev `state` payload when the brain supports vision; transcript-only decision becomes screen-aware. `needs_screen` question deleted (pipeline always sends it). |
| U2 | Talk vs Agent modes | `route` gains `agent` (computer-use loop, confirms once per app) alongside `act` → redefined as single-action (click/type/focus). Wake prefix `"wisp agent"` or long-press routes straight to agent, skipping Jev. Most utterances land Talk/answer and end there. |
| U3 | Goal memory | `wisp/goals.py` — active goal `{text, app, steps[], status}`; continuations join by same-focus or topic overlap (reuse `trajectories._related`); 10-min TTL `[agent] goal_ttl_s`; persists to state.json → panel shows "working on: …". |
| U4 | Confirm-once + Jev slimming | `state.confirmed: set` of `(tool, app)`; `app`/`action` Jev questions deleted, `plan` slot added (goal + first_step hint in tool vocabulary). Clarify demoted to parse-failure escape hatch. |
| U5 | Voice backchannel | `ASK_USER:` reply → TTS + `awaiting_voice` status; next utterance resumes the same goal. Conversation, not modal. |

## Verification

Replay the Robinhood sequence:
`"check my robinhood account"` → `"open it in a browser"` →
`"command t"` → `"type robinhood.com"` → `"click GDX"`. Acceptance:
all five join one goal, zero clarify cards, ≤1 confirm total, and the
final click lands inside the GDX row region — verified by trajectory.

## Open questions

- Wake prefix vs long-press for Agent mode — prefix is implemented
  entirely in routing text, long-press needs the hotkey layer; start
  with the prefix.
- Clicky's per-app memory tail parallels our MEMORY.md block — if the
  two collide on size, memory wins and the app tail is dropped.
