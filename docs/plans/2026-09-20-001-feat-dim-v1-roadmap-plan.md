---
title: "feat: Wisp v1.0 roadmap — real answers, context, memory, release"
created: 2026-09-20
type: feat
origin: docs/brainstorms/2026-09-18-dim-autonomous-assistant-requirements.md
supersedes-partially: docs/plans/2026-09-18-001-feat-dim-autonomous-assistant-plan.md
status: "superseded by 2026-10-04-0100-feat-wisp-unified-plan.md"
---

# feat: Wisp v1.0 roadmap

## Summary

Wisp v0.2 ships a working skeleton: resident daemon, Jev routing, toolbelt,
`ori opencode` agents, Quickshell plugin, weekly learning loop. This plan
carries the repo to a **v1.0 release**: every user-facing path produces real
output (no canned text), Jev sees tiered screen context, sessions persist
across restarts, the whole loop is verified end-to-end live, and the project
is packaged and merged as a public release.

Jev stays the decision model (user directive — a Laya swap was considered
and declined; see Alternatives). Real text answers come from a second
OpenRouter chat model — Jev routes, the chat model answers.

---

## Problem Frame

Today three seams produce fake or missing output:

1. `answer` route returns canned strings (`wisp/pipeline.py::answer_text`) —
   "what's this error?" gets a shrug.
2. Jev's `state` is transcript + active-window title only — no screen
   awareness despite `screenshot` existing as a tool.
3. No conversation memory — every trigger is stateless; follow-ups
   ("repeat that", "yes do it") can't work.

And the release gaps: GTK `dim-overlay` still ships as fallback, no real
voice run is recorded as verified, `feat/dim-assistant` is unmerged, and
there is no tagged release.

## Requirements

- **R1** — `answer` route produces real generated text via an OpenRouter
  chat model; optional screen image attached when relevant.
- **R2** — Jev decision `state` carries tiered context: active window
  class/title + workspace always; screenshot bytes only when needed.
- **R3** — Conversation turns persist to disk (jsonl) and feed follow-up
  context; survives daemon restart.
- **R4** — One real `Super+D` end-to-end run verified per surface
  (launch, tool, answer, choice) before v1.0 is tagged.
- **R5** — GTK `dim-overlay` removed; Quickshell plugin is the only UI.
- **R6** — `feat/dim-assistant` merged via PR; `v1.0.0` tagged; README
  reflects released state.

### Scope Boundaries

**Out of scope (v1.0):** wake-word listening, pixel-level GUI control,
Rowboat Personal bridge, model fine-tuning, non-Linux platforms.

**Deferred to follow-up work:** Laya local decision model (revisit if
OpenRouter cost/latency/privacy becomes a problem), interactive `ori
opencode` TUI spawn mode, rich TTS beyond espeak.

---

## Key Technical Decisions

- **KTD-1 — Jev retained as router.** The decisions API (noul/choice/score)
  is a good fit for routing and costs ~$0.00005/call. A local Laya swap
  adds a transformers/HF dependency for marginal benefit — declined this
  phase (see Alternatives).
- **KTD-2 — Answer model is a separate OpenRouter chat call.** Jev cannot
  emit text by design. `answer` route POSTs to
  `https://openrouter.ai/api/v1/chat/completions` with the transcript,
  session context, and optionally a screenshot. Model configurable via
  `[agent] answer_model` in config.toml; default a cheap vision-capable
  OpenRouter model (pick at implementation; must accept `image_url`
  content parts).
- **KTD-3 — Tiered screen context.** Text context (window class/title,
  workspace, harness profile) always goes to Jev. A `needs_screen` noul
  question is added to `JEV_QUESTIONS`; when it scores ≥0.7 or the route
  resolves to `answer`, `grim` captures the focused output and the PNG is
  sent to the answer model as a base64 `image_url` part. Screenshot is
  never sent to Jev.
- **KTD-4 — Session log at `~/.local/share/wisp/session.jsonl`.**
  Each completed turn appends `{ts, transcript, route, reply, result}`.
  The last N turns (default 8, `[agent] session_turns`) are prepended to
  both the Jev `state` and the answer-model messages, so "do it" and
  "repeat that" resolve. Read-only on daemon start — no in-memory cache
  to sync.
- **KTD-5 — GTK overlay deleted, not deprecated.** The Quickshell plugin
  is proven on the live bar; keeping `dim-overlay` as a fallback doubles
  the UI surface to maintain. Removal happens only after R4's verified
  run.
- **KTD-6 — v1.0 = merge + tag, not a feature gate.** Remaining ambition
  (wake word, GUI control, Rowboat) is post-v1.0 roadmap, not a blocker.

## High-Level Technical Design

```
Super+D → wispd listen → record → whisper ──► Jev (state: transcript +
                                              session tail + window text)
                                                │        │ needs_screen≥0.7
                     ┌──────────┬───────────────┼────────┤
                     ▼          ▼               ▼        ▼
                  launch      tool           agent    answer
                                                    │ grim PNG (b64)
                                                    ▼
                                              chat completions
                                                    │
                                                    ▼
                                              reply → state.json
                                              → espeak (optional)
                                              → session.jsonl append
```

Session memory is append-only JSONL; reads take the tail. Screenshot files
are transient (`$XDG_RUNTIME_DIR/wisp/screen.png`), deleted after the
answer call.

---

## Implementation Units

### U1. Real answers via OpenRouter chat

**Goal:** `answer` route generates a real reply instead of canned text.
**Requirements:** R1
**Dependencies:** none
**Files:** `wisp/pipeline.py` (new `ask_chat()`, rework `run_once` answer
branch, drop `answer_text`), `dim/config.py` (`answer_model` default),
`tests/test_pipeline.py`
**Approach:** stdlib `urllib` POST to chat completions, mirroring
`ask_jev`'s auth/headers. Messages: system line ("You are Wisp, a terse
desktop assistant…"), session tail as prior turns, transcript as user
message. Timeout 30s; failure falls back to the canned text and result
`ANSWER_FAILED`.
**Test scenarios:**
- Happy: mocked 200 → `run_once` transitions `done` with `answer` set to
  the model reply, not the canned string.
- Happy: `answer_model` absent from config → uses the default constant.
- Error: HTTP 500 / timeout → `ANSWER_FAILED`, canned fallback used,
  no exception propagates.
- Edge: empty choices array in response → fallback text.
**Verification:** `wispd trigger` on "what can I say" produces a real
reply in `state.json`'s `answer` field and the bar widget shows it.

### U2. Persistent session memory

**Goal:** turns persist to `session.jsonl` and feed follow-up context.
**Requirements:** R3
**Dependencies:** U1 (answer consumes the same session tail)
**Files:** `wisp/session.py` (new: `append_turn`, `tail`), `dim/config.py`
(`SESSION` path, `session_turns` default), `wisp/pipeline.py`
(read tail into Jev `state` + chat messages; append on `done`),
`tests/test_session.py`
**Approach:** append-only JSONL mirroring `decisions.jsonl` conventions;
`tail(n)` reads the file and returns the last n records; no locking
needed (single daemon writer).
**Test scenarios:**
- Happy: append 3 turns → `tail(2)` returns last 2 in order.
- Edge: missing file → `tail` returns `[]`, no error.
- Edge: corrupt last line → skipped, earlier lines still returned.
- Integration: after a `run_once` answer turn (all IO mocked), the session
  file contains a record with transcript + reply.
**Verification:** restart daemon, say "what did I just ask" — the reply
references the prior transcript.

### U3. Tiered screen context

**Goal:** Jev state always includes window text; answers get a screenshot
when needed.
**Requirements:** R2
**Dependencies:** U1
**Files:** `wisp/pipeline.py` (`needs_screen` noul question, grim capture
helper, image part in `ask_chat`), `dim/config.py` (`screenshot` toggle),
`tests/test_pipeline.py`
**Approach:** add `"needs_screen": {"type": "noul", "instructions": "Does
fulfilling this request require seeing the screen contents?"}` to
`JEV_QUESTIONS`. Capture via `grim -o <focused>` into `$XDG_RUNTIME_DIR/
wisp/screen.png`; attach as `image_url` only when
`noul ≥ 0.7 OR route == answer AND config allows`. Delete the PNG after
the call.
**Test scenarios:**
- Happy: `needs_screen` 0.9 + answer route → `ask_chat` payload contains
  an `image_url` part with base64 PNG.
- Happy: `needs_screen` 0.2 + launch route → no capture, no image part.
- Error: grim missing/fails → answer call proceeds text-only.
- Edge: `[agent] screenshots = false` → never captures.
**Verification:** "what's wrong on this screen" with an error dialog up
produces a reply referencing the dialog text.

### U4. GTK overlay removal + plugin hardening

**Goal:** Quickshell plugin is the sole UI; delete `dim-overlay`.
**Requirements:** R5, partial R4
**Dependencies:** U1–U3 landed and one manual `Super+D` smoke passed
**Files:** `dim-overlay` (delete), `wispd` (drop `OVERLAY_BIN` install +
`_gtk_choice` fallback), `dim/config.py` (drop `OVERLAY_BIN`),
`wisp/pipeline.py` (drop GTK overlay spawn/terminate),
`tests/stage_test.sh`, `README.md`, `.github/workflows/test.yml`
(compile list)
**Approach:** choice interaction goes exclusively through daemon IPC
(`wait_for_choice`); when the plugin isn't running, low-confidence turns
cancel with a notify instead of GTK buttons.
**Test scenarios:**
- Happy: `run_once` with mocked record/transcribe/Jev completes with no
  `dim-overlay` binary present.
- Edge: `wait_for_choice` returns None at timeout → CANCELLED, no GTK
  spawn attempted.
- Regression: `wispd install` succeeds with no `dim-overlay` source file.
**Verification:** grep finds no `dim-overlay`/`OVERLAY_BIN` references;
plugin still shows overlay during a live trigger.

### U5. Live end-to-end verification pass

**Goal:** R4 evidence — real runs on the actual machine recorded in the
plan/issue.
**Requirements:** R4
**Dependencies:** U1–U4
**Files:** `docs/HANDOFF.md` (update), `README.md` (verified-usage notes)
**Approach:** manual verification checklist run on omarchy-max (or
whichever host): launch route, tool route (screenshot/notify), answer
route with and without screenshot, choice flow via bar widget, agent
spawn via `ori opencode`. Record transcripts + results; file fixes as
bugs rather than papering over.
**Test expectation:** none — manual verification unit; checklist lives in
the unit approach, results appended to HANDOFF.md.
**Verification:** checklist complete with at least one real success per
route type logged in `decisions.jsonl`.

### U6. Release: merge, tag, README

**Goal:** v1.0.0 lands on master.
**Requirements:** R6
**Dependencies:** U5
**Files:** `README.md`, `pyproject.toml` (version 1.0.0), PR on
`feat/dim-assistant`
**Approach:** PR review of the full branch diff, merge to master, tag
`v1.0.0`, GitHub release notes from the unit list. README gains a
"verified on Omarchy/Asahi + Hyprland" line and the roadmap section
points at post-v1.0 items.
**Test expectation:** none — release mechanics.
**Verification:** `gh release view v1.0.0` resolves; fresh-clone install
instructions work.

---

## Alternatives Considered

- **Laya (`convaiinnovations/laya`) instead of Jev.** Open Apache-2.0
  421M ModernBERT decision model, same typed-questions shape, runs local —
  no key, no network, free. Declined by user directive ("use jev") and on
  carrying cost: adds transformers/HF + ~1.7GB weights to a zero-dep
  stdlib codebase. Revisit if OpenRouter cost, latency, or privacy
  becomes an issue; `ask_jev` is the only call site, so the swap stays
  cheap.
- **Local chat model for answers** (llama.cpp/ollama). Fully offline but
  a second heavy runtime + model management; OpenRouter keeps "all
  OpenRouter" consistency with the agent path. Deferred, not rejected.

## Risks & Dependencies

- **OpenRouter chat model choice** — the answer model must accept
  `image_url` parts; pick a cheap vision model at implementation and keep
  it behind `answer_model` config.
- **Screenshot privacy** — images leave the machine for OpenRouter on
  answer routes; `screenshots=false` config escape hatch, documented.
- **`grim` on the focused output** — behavior with multiple monitors
  verified in U5.
- **Session log growth** — tail-read only; cap file at ~1MB by rotating
  (truncate beyond last 200 turns) if it becomes an issue.

## Sources & Research

- Jev decisions API verified live this session: types `noul | choice |
  score` only; `detail` free-text question 400'd and was removed.
- Laya model card: huggingface.co/convaiinnovations/laya (421M, Apache
  2.0, `pip install laya`, `agent.predict(state, questions)`).
- OpenRouter chat completions: `api/v1/chat/completions`, standard
  OpenAI-shaped messages with `image_url` support on vision models.
