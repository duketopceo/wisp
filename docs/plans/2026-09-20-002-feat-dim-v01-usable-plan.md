---
title: "feat: Dim v0.1 usable — latency, Clicky presence, guarded computer-use loop"
created: 2026-09-20
type: feat
origin: docs/plans/2026-09-20-001-feat-dim-v1-roadmap-plan.md
---

# feat: Dim v0.1 usable

## Summary

Current build is "borderline unusable" (user report): slow-feeling
pipeline, weak actions, no visible presence. This plan delivers a
**usable v0.1**: a fast open-weights answer/action model alongside Jev,
a persistent Clicky-style companion widget, and a bounded guarded
computer-use loop so Dim can actually *do* multi-step desktop tasks —
with the existing risk-tier system as guardrails.

Model split (user directive): **Jev routes; an open-source OpenRouter
flash-class model answers and acts.** Heavy development tasks go through
`ori opencode` as today — model choice there is the user's call.

## Problem Frame

Three concrete failure surfaces, all confirmed this session:

1. **Latency** — `record(5s) → whisper(small.en) → Jev → act` is serial;
   nothing acknowledges the trigger until seconds later.
2. **Weak actions** — Jev can only classify; anything beyond "open X"
   degrades to transcript-as-detail hacks or cancels.
3. **No presence** — a bar icon and transient overlay; no sense Dim is
   alive, listening, thinking, or working between triggers.

## Requirements

- **R1** — Trigger feedback is instant: overlay/state flips to
  `listening` before the first audio frame is captured.
- **R2** — Answers/actions use an open-weights OpenRouter model,
  flash-class latency, configurable via `answer_model` (default
  `meta-llama/llama-4-maverick` — open weights, vision-capable, fast).
- **R3** — A Clicky-style companion: always-visible floating presence
  (quickshell overlay kind), idle orb → listening/thinking/acting/done
  states, click to expand transcript/answer/agent panel.
- **R4** — New `act` route: bounded multi-step computer-use loop — model
  emits tool calls against the existing toolbelt schema; every call
  passes the risk-tier gate; mutating/shell require user confirm via
  choice widget; hard cap of 8 steps; abort on repeated failure.
- **R5** — Guardrails preserved end-to-end: denylist + `allow_shell` +
  risk threshold unchanged for the loop path; every loop step logged to
  `decisions.jsonl`.
- **R6** — Verified usable: live `Super+D` runs for launch, answer,
  and a 2+ step `act` task recorded in HANDOFF.md.

### Scope Boundaries

**Out of scope:** wake word, pixel-coordinate clicking (tools are
semantic: launch/type/workspace/etc.), Rowboat
bridge, mobile/remote triggers.

**Deferred:** true vision-driven pixel
control, TUI watch-mode for agents, per-app voice macros.

---

## Key Technical Decisions

- **KTD-1 — Two-model runtime.** Jev (~$0.00005, <1s) classifies; the
  chat model generates. For `act`, the same chat model gets a `tools`
  array and the loop executes its tool calls. No third model.
- **KTD-2 — Open-weights default.** `meta-llama/llama-4-maverick` as
  `answer_model` default: open weights, multimodal (image_url), fast
  providers on OpenRouter. `qwen/qwen3-vl-235b-a22b` noted as fallback.
- **KTD-3 — `act` loop is a tool-call loop, not a new agent.** The model
  sees tool schemas derived from `tools.describe()`; each proposed call
  re-enters `execute()`-equivalent gating (denylist, allow_shell, risk
  tier). Loop state lives in `state.json` (`acting`, step counter) so
  the companion widget shows progress.
- **KTD-4 — Companion = quickshell overlay kind.** Same plugin, new
  `Companion.qml`: small floating window anchored bottom-right of the
  focused monitor, renders daemon `state.json` (already polled by
  `DimService`). Click toggles an expanded card reusing BarWidget rows.
- **KTD-5 — Latency: acknowledge first, work second.** `state.transition(
  "listening")` already fires pre-record; extend to publishing partial
  stages (`transcribing`, `deciding`, `acting`) to the companion and cut
  dead time by running the whisper call with `-nt` and streaming level.
  No architectural async rewrite in v0.1.

## High-Level Technical Design

```
Super+D ─▶ listening (orb breathes) ─▶ whisper ─▶ Jev route
                                        │
              launch ─ tool ─ agent ─ answer ─ act ─ clarify
                                              │       │
                                   chat model (text)  ▼
                                              ┌─ tool-call loop ≤8 ─┐
                                              │ model → tool call   │
                                              │ → risk gate → run   │
                                              │ → result → model    │
                                              └─────────────────────┘
                                    every step → state.json → orb
```

---

## Implementation Units

### U1. Fast answer model + latency pass

**Goal:** sub-second-feeling responses; instant trigger feedback.
**Requirements:** R1, R2
**Files:** `dim/config.py` (answer_model default → `meta-llama/llama-4-maverick`),
`dim/pipeline.py` (state transitions already staged; ensure `listening`
publishes before `record()` opens the mic — it does; add `thinking`
state around ask_jev/ask_chat), `dim/state.py` (no change expected),
`tests/test_session.py`, `README.md`
**Approach:** config default swap + verify image_url support holds on the
new model; add a `timing` field to decisions.jsonl records (record_ms,
stt_ms, jev_ms, act_ms) so "slow" becomes measurable.
**Test scenarios:**
- Happy: default config → `answer_model` resolves to the open-weights slug.
- Happy: decisions record carries per-stage timings.
- Edge: `answer_model` set in config.toml → honored over default.
**Verification:** decision log shows stage timings; answer latency
visible per turn.

### U2. Clicky companion widget

**Goal:** persistent floating presence showing live state.
**Requirements:** R3
**Files:** `shell-plugin/Companion.qml` (new), `shell-plugin/manifest.json`
(add overlay kind entry or second component), `shell-plugin/BarWidget.qml`
(click opens companion), `docs/HANDOFF.md`
**Approach:** quickshell `PanelWindow` overlay, bottom-right anchor,
~48px orb. States map from `state.status`: idle dim ring, listening
breathing fill (uses `level`), thinking spinner, acting pulse, done
flash, error red. `DimService` already polls `state.json` — reuse.
Click toggles expanded card (transcript/answer/choices, reusing the
BarWidget content block).
**Test scenarios:**
- Manifest valid JSON; Companion.qml parses (`qmllint` or load check via
  plugin reload, verified manually).
- Edge: missing state.json → orb renders idle, no crash.
**Verification:** orb visible on the live bar/workspace; press Super+D →
orb breathes; done state flashes.

### U3. `act` route — guarded computer-use loop

**Goal:** multi-step tasks ("open discord and go to workspace 3", "type
this into the focused window") run through the toolbelt under the model's
control, bounded and gated.
**Requirements:** R4, R5
**Files:** `dim/pipeline.py` (`act` route → `run_act_loop`), new
`dim/act.py` (loop, tool schema builder, step log), `dim/tools/__init__.py`
(`tool_schemas()` — OpenAI tools format from REGISTRY),
`tests/test_act.py`
**Approach:** Jev gains an `act` criterion ("multi-step or imperative
desktop task"). `run_act_loop(detail, cfg)` posts chat completions with
`tools=tool_schemas()`, `tool_choice=auto`; each returned tool_call maps
to `tools.run` after the same gates `execute()` applies (denylist,
allow_shell, mutating→needs a `confirmed` flag from the choice widget or
skips). Cap 8 steps or 2 consecutive tool errors → abort. Steps logged
to decisions.jsonl and mirrored into `state.tasks` for the companion.
**Test scenarios:**
- Happy: mocked model returns tool_call `launch discord` → loop runs
  tool, returns result to model, model finishes with text → DONE.
- Guard: tool_call `shell rm -rf /` → REFUSED recorded, loop continues
  or aborts per policy; shell never executes.
- Guard: mutating tool without confirmation → skipped, model informed.
- Edge: model returns 3 consecutive errors → ABORTED.
- Edge: loop hits step cap → ABORTED (max steps).
- Integration: `route=act` answers dict dispatches into the loop via
  `execute()`.
**Verification:** "open discord and switch to workspace 2" completes both
steps, logged in decisions.jsonl.

### U4. Companion/pipeline error surfacing

**Goal:** failures are visible, not silent — error state reaches the orb
and bar.
**Requirements:** R3 (presence), supports R6
**Files:** `dim/pipeline.py` (error state already exists — ensure
`error` field populates state.json on every failure path),
`shell-plugin/Companion.qml` (error style), `dim/ipc.py` if needed
**Approach:** verify every `except` in `run_listen` sets
`state.transition("error", error=...)`; companion renders error red for
~5s then returns to idle.
**Test scenarios:**
- Error: whisper binary missing → state.json shows `error` with message.
- Error: Jev HTTP failure → `error` state, not silent hang.
**Verification:** kill whisper path → trigger → orb shows error state.

### U5. Live verification + docs

**Goal:** R6 evidence — real runs recorded.
**Requirements:** R6
**Dependencies:** U1–U4
**Files:** `docs/HANDOFF.md`, `README.md`
**Approach:** checklist on the live machine: launch, answer (text-only),
answer (screenshot), choice pick, act 2-step, agent spawn. Record
transcripts/results; update HANDOFF.
**Test expectation:** none — manual verification.
**Verification:** one success per route logged in decisions.jsonl;
HANDOFF updated.

---

## Risks & Dependencies

- **`act` loop safety** — model-proposed tool calls get the identical
  denylist/allow_shell/risk gates; mutating tools degrade to skip when
  no chooser is wired rather than executing.
- **Tool schema drift** — `tool_schemas()` must derive from the registry
  so new tools appear automatically; a static list will rot.
- **Cost** — act loops burn chat-model tokens per step; cap 8 + open
  weights default keeps it cheap.
- **Companion anchoring** — quickshell overlay placement on multi-monitor
  (eDP-1 + DP-3 dock) verified in U5.

## Sources & Research

- OpenRouter chat completions + `tools`/`tool_choice` — OpenAI-compatible.
- Open-weights vision-capable candidates: `meta-llama/llama-4-maverick`
  (default), `qwen/qwen3-vl-*` family (fallback).
- Hey Clicky: cursor-side companion presence + voice-spawned agents —
  the orb is the presence element adapted to quickshell.
