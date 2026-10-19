---
title: Wisp autonomous-agent parity (heyclicky-class agent loop + dictation)
type: feat
date: 2026-10-09
---

# Wisp autonomous-agent parity

## Summary

Rebuild wisp around a real autonomous agent loop instead of a one-shot
route→execute pipeline, clone the heyclicky interaction model (talk →
agent acts on the machine, background-delivery input, legible live
state), add LLM-aware dictation (say the idea, get finished text), and
audit the entire interaction surface so no button, chip, voice path, or
card can silently do nothing. Everything runs on cheap OpenRouter models
with Jev kept as router/verifier, not as a per-decision gate.

## Problem Frame

The user reports wisp is "totally useless" next to heyclicky and that
clicking "no" on the "was that right?" label row did nothing. Two
distinct failures feed that verdict:

1. **Interaction surface has dead paths.** Verified in-tree:
   `WispService.sendChoice` runs `wispd choice` through a shared
   `Process` (`actionProc`) that has no `onExited`, no stdout/stderr
   collector — every daemon refusal (`stale_prompt`, `not_offered`,
   `bad_index`) and every subprocess failure is invisible. The
   `label`/`interrupt`/`trigger` paths share the same fire-and-forget
   Process. Suggestion-card chips are dead by contract: `suggest.py`
   publishes `choices` under `status: "suggestion"` with no `prompt_id`,
   but `acceptChoice` drops anything whose status isn't
   `awaiting_choice` or whose `promptId` is empty — the click never
   leaves the shell.

2. **The pipeline is not an agent.** A turn is: press → STT → Jev
   decides a route → dispatch once → done. `act.py`'s
   `run_act_loop` is a real tool loop, but it is reached only when Jev
   picks `route=act`, it has no multi-turn goal memory inside the loop,
   and Jev's structured questions sit *in front of* every turn —
   deciding whether to act, not how. Confirm cards pop a modal per
   gated tool and wait up to 120 s; voice answers were patched on, but
   the model still can't converse inside the loop. The result matches
   the user's words: "it tries and fails to do, doesn't hold a
   conversation."

HeyClicky works because the shape is different: a streaming agent loop
on a smart model, AX-first background-delivery tools (never steals the
pointer), risk-tiered gates only at irreversible boundaries, spoken
follow-ups on live cards, and ramble-to-draft dictation. Wisp already
has most of the machinery — tool registry with risk tiers,
`PromptBroker`, `CancelToken`, session/goals memory, CUA driver, ghost
cursor, MCP client, clicklab/arena training. This plan rewires it into
that shape.

## Research Findings

### Heyclicky (target product — confirmed via `farzaa/clicky` OSS predecessor + extracted runtime prompt)

- **Input:** PTT hotkey (Ctrl+Option), double-tap for hands-free
  dictation, `heyclicky agent` wake phrase to spawn a background agent,
  voice follow-up on live agent cards (hold to talk, release to send,
  tap/Esc cancels). No always-listening; screen captured only on press.
- **Acting:** AX-first tools (`click`, `right_click`, `set_value`,
  `type_text`, `press_key`, `hotkey`, `scroll`, `page`,
  `get_window_state`) all forced `delivery_mode: "background"` —
  clicks/type land without stealing focus or the pointer. Window-scoped
  pixel clicks are the escalation. Desktop-scope real-cursor input,
  drag, and double-click are blocked at the driver level.
- **Safety:** asks a clarifying question instead of guessing; holds
  when told "wait"; stops before purchases/sends/deletes/irreversible;
  approval cards ("Allow / Not now / Always approve") are batched at
  boundaries, not per-tool.
- **Dictation ("ramble-to-draft"):** streaming STT ~450 ms into any
  app, grammar/spelling cleanup, a learned correction dictionary, and —
  the headline — a screenshot + memory → writes a reply in your voice.
  Newlines are collapsed when the focused app is a terminal (dictated
  text can never execute as a command).
- **Agents/personas:** named "Clickys" with faces, memory, jobs;
  routines (scheduled agents); file outputs shown as thumbnails on the
  agent card; multi-account integrations (Gmail, Calendar, Notion).
- **Stack:** Claude Sonnet/Opus via SSE, AssemblyAI streaming STT +
  Whisper/Apple fallbacks, ElevenLabs TTS, ScreenCaptureKit shots
  ≤1280 px, Cloudflare Worker proxy. macOS only, closed commercial tier
  (free 25+25 msgs, Pro $20, Max $100).
- **What to clone vs adapt vs skip** is decided per-feature in Units;
  the load-bearing borrow is `delivery_mode: background` and
  boundary-gated confirms, not the brand surface.

### Dictation prior art (wordink / VoiceInk)

- `WordInk` (`~/Documents/github/personal/WordInk`, the owner's own
  fork of `groq_flow`) — Rust sans-I/O core + WASM SDK; `legacy/` holds
  a working Python dictation app (`text_inserter.py` = clipboard-paste
  insert, Groq whisper STT). No LLM-rewrite layer. wisp's
  `stage_execute` already opportunistically `import wordink` for its
  `TextInserter` — that is a live integration point, not a dependency
  on a released package.
- `Beingpax/VoiceInk` (GPL) — the blueprint for LLM-aware dictation:
  post-STT enhancement layer (cleanup/reformat/rewrite modes) and
  **Power Mode** = per-app/URL auto profiles (model + prompt +
  auto-send). Maps directly onto hyprland `activewindow.class`.
- So "say the idea, it writes the email" = wisp STT → brain model
  rewrite (per-app profile) → insert. The insert mechanism and STT are
  already in-tree.

### Wisp audit (full surface sweep, completed during planning)

Every surface element traced end-to-end. **Working:** bar
left/middle/right gestures, panel open/close, settings save + connect
dispatch, keyboard submap (Esc/Enter/1..n), voice-pick answers,
PromptBroker, confirm timeouts, act loop (bounded, real), tools
registry (21 tools, 4 tiers), CUA safety guard, MCP dispatch.

**Dead or silent-fail, ranked:**

1. `sendChoice` local gate — `acceptChoice` requires
   `view.promptId===pid` + `status==="awaiting_choice"` + pick ∈
   choices; any staleness → silent `return false`, zero IPC, zero UI
   signal (`state.js:66-70`, `WispService.qml:124-130`). Confirm
   timeout resolves as **deny** server-side; the card can still render
   while the prompt is already dead.
2. Cleared-choices race — the deny chip reads `service.choices[len-1]`
   live (`Bubble.qml:84`); an in-flight diff emptying `choices` sends
   `undefined` → local reject.
3. Daemon-side refusal invisible — `stale_prompt` (timeout, daemon
   restart wiping the in-memory broker, another emitter answering)
   replies go to `actionProc`, which has **no onExited/stdout/stderr**
   (`WispService.qml:416-419`).
4. Shared-Process absorption — `run()` sets `command` then
   `running=true` with no busy check; a second action while a spawn is
   alive is silently dropped.
5. Suggestion chips dead on **every** QML surface — `suggest.py`
   publishes `status:"suggestion"` + choices but **no prompt_id**;
   `acceptChoice` kills them all. Only the TUI can answer suggestions.
6. Label row ("was that right?" yes/no) — IPC path works, but the
   reply (`"nothing to label"`, errors) is swallowed by the same
   actionProc; the row gives no ack.
7. Debug shell `Restart daemon`/`Stop` buttons call `win.svc` which
   does not exist (`shells/debug/shell.qml` defines `svcCtl`) — clicks
   do nothing.

**New discovery — an unidentified external process is driving the
daemon socket.** `wispd.log` shows `ipc task_status` every ~3 s
continuously and recurring `choice(stale)→choice(ok)→interrupt`
bursts at ≤5 ms spacing — no single `WispService` (serialized
`actionProc`, ~10 ms spawn) and no human keypress can produce that.
Nothing in-repo polls `task_status`. IPC logging records cmd+ok only —
no `SO_PEERCRED` attribution. U1 must instrument peer pid/uid
(`ipc._serve`/`_handler`) and identify the emitter before assuming the
bursts are UI bugs.

**Backend is real, not stubbed.** The rebuild is rewiring, not a
greenfield agent: act loop, typed-decision router, confirm gating,
CUA guard, MCP, memory/recall/skills/trajectories/agents all exist and
wire together. The gaps are: no cross-turn autonomous loop, no
in-loop conversation, suggestion↔QML bridge, lifecycle feedback, and
`voice.enabled=false` default.

## Requirements

**Interaction lifecycle**
- R1. Every user action on every surface (bar click/middle/right, panel
  chips, card buttons, stop, label row, connect, save, onboard steps)
  produces a visible in-flight ack and a rendered terminal state
  (done/failed/cancelled + reason). No path may silently no-op.
- R2. Daemon refusals (`stale_prompt`, `not_offered`, `bad_index`,
  `busy`, tool errors) surface in the UI as typed errors, not silence.
- R3. Suggestion cards, confirm cards, and label rows all resolve
  end-to-end through one lifecycle; a clicked choice clears the card
  optimistically and reconciles with the daemon's answer.

**Autonomous agent loop**
- R4. A voice request becomes a multi-turn, multi-step agent run:
  observe → plan → act → verify → repeat, with session/goal memory
  fed each step and conversational follow-ups inside the run.
- R5. Jev stays as the cheap pre-router and post-hoc verifier ("did it
  do the thing, was the chosen action optimal"); it does not gate each
  step.
- R6. The loop selects tools dynamically per step — structured
  integrations (MCP/strata, DOM-mode, app APIs) before CUA; CUA before
  asking the user to do it.
- R7. The loop recovers from step failures (retry, alternate tool,
  report why) instead of ending the turn on the first error.

**Autonomy + trust**
- R8. Action tiers T0–T3: T0 observe/navigate never confirms; T1
  reversible local runs confirm-free but renders in-flight + undo ref;
  T2 irreversible/external confirms at batched checkpoints showing the
  artifact; T3 money/credentials/identity pause the agent for a human
  handoff. Tiers are declared on the tools registry, linted in CI.
- R9. The user can interrupt at any time — Esc, middle-click, spoken
  "stop" — and in-flight input injection halts mid-stream.
- R10. A running turn shows: intent echo (parsed, not raw ASR), the
  plan/step cursor, the in-flight action + target, an always-visible
  interrupt affordance, and a terminal mutation summary.

**CUA**
- R11. Input delivery is background-first: per-window/`window-scope`
  delivery before real-pointer; real-pointer CUA is the escalation and
  is the only mode allowed to move the user's cursor.
- R12. The user never fights the agent for the pointer — real-pointer
  runs yield instantly on real user input.

**Dictation**
- R13. Dictation modes: verbatim, cleanup (grammar/filler), and
  compose (ramble → finished text in target app's voice/context).
- R14. Per-app dictation profiles keyed on hyprland window class
  (terminal collapses newlines; email wraps; Slack stays terse).
- R15. Dictated output is always a draft artifact — it inserts at the
  cursor with undo, never auto-sends across a boundary.

**Model + cost**
- R16. Default brain is a cheap OpenRouter model (current
  `google/gemini-2.5-flash` is the floor); a per-turn/step spend cap
  aborts legibly. GPT-6 Astra is never a choice. Local backends keep
  working via `wisp-backend`.
- R17. A per-run step cap and spend cap exist; hitting either renders a
  bounded abort with the mutation list so far.

**Verification**
- R18. Clicklab/arena gains adaptive coverage: every repaired silent
  path gets a UI/component test; the agent loop gets golden-task evals
  (draft email, browse/navigate, file op, app action) run on both
  live-session and clicklab fixtures.
- R19. Jev verifies loop outcomes (did the goal complete; was the
  action optimal) as a post-hoc judge feed into labels/recipes.

## Key Technical Decisions

- **KTD1 — Lifecycle before autonomy.** Every existing dead/no-op path
  is fixed and covered by a UI test before new capability lands. The
  "clicked no → nothing" bug is the acceptance fixture, not an aside.
- **KTD2 — One lifecycle stream.** Replace per-card confirm wiring
  with a unified action event stream (`queued → in_flight → done/failed
  /cancelled + reason + undo_ref`). The confirm card becomes a *state*
  in that stream, not a separate widget path. This is what removes
  silent dead ends structurally.
- **KTD3 — Jev demoted to router+verifier.** Keep `typesafe/jev-*` on
  `/alpha/decisions` for the cheap route pick and post-run verdict.
  Remove it from per-step decisions — the brain model owns in-loop
  tool choice. This is the "decide what to do, not whether to do" ask.
- **KTD4 — Single conversational agent loop.** `run_act_loop` grows
  session turns, goal memory, and an observe→act→verify cycle with a
  mid-loop "ask the user" tool (that is the conversational confirm
  card, driven by the model, not the pipeline). Voice answers and
  typed answers both resolve it.
- **KTD5 — Background delivery first.** Add a `delivery` concept to
  the CUA driver: `background` (uinput/wtype/CDP/AT-SPI where a backend
  exists) default, `pointer` escalation only when background can't
  reach the target. Matches heyclicky's `delivery_mode` contract;
  `cua.confirm=always` already promotes pointer tools.
- **KTD6 — Dictation as a mode, not a route.** Dictation lives behind
  an explicit mode toggle (or a `dictate` verb), with a per-app
  profile dictating which rewrite applies. Reuse WordInk legacy's
  clipboard-paste `TextInserter` approach — keep the `import wordink`
  opportunistic path, add a `wtype`-paste fallback in-tree.
- **KTD7 — Terminal newline guard.** Dictated text destined for a
  terminal-class window collapses newlines to spaces — spoken text can
  never execute as a command. Mirrors heyclicky/VoiceInk behavior.
- **KTD8 — Smart-cheap model matrix.** Brain default stays a cheap
  OpenRouter model; tool-heavy steps may escalate one tier within the
  spend cap; Jev stays jev-1.13; local `ornith`/`uitars` keep working
  through `wisp-backend`. No premium model ids in defaults.
- **KTD9 — Tool taxonomy is enforced.** `wisp/tools/__init__.py` tiers
  gain `reversibility` + `externality` metadata; a CI lint fails when a
  registry entry lacks tier data. The taxonomy audit is load-bearing,
  not optional.

## Implementation Units

### U1. Interaction lifecycle audit + dead-path repair
- **Goal:** every surface action produces ack + terminal state; the
  seven confirmed dead paths get fixed and covered; the external
  emitter gets identified.
- **Files:** `shell-plugin/WispService.qml` (actionProc result
  surfacing, per-action Process or queue + busy guard),
  `shell-plugin/lib/state.js` (`acceptChoice` admits `suggestion`
  status + suggestion picks that carry their own key),
  `shell-plugin/components/{NowTab,OverlayLayer,Bubble}.qml`,
  `shells/debug/shell.qml` (`win.svc` → `svcCtl`),
  `wispd` (choice/label/interrupt return structured results),
  `wisp/ipc.py` (peer-credential logging),
  `wisp/suggest.py`, tests under `tests/test_*` + `tests/qml/`.
- **Repair list** (from the audit):
  - `run()` gains a completion path: stdout/stderr + exit code → a
    `lastAction` view field; daemon refusals render as typed errors.
  - Serial-guard `actionProc` — a second action while one is in flight
    queues or refuses visibly, never drops silently.
  - `acceptChoice` drops emit a UI nudge ("that question expired")
    instead of `return false` into the void.
  - Deny/allow chips snapshot their pick at render time (no live
    `choices[i]` reads at click time).
  - Suggestion picks route straight through (`suggestion:` needs no
    prompt_id — the daemon already intercepts them pre-broker).
  - Label clicks ack ("noted"); `actionProc` surfaces `learn` replies.
  - Fix `win.svc` → `svcCtl` in the debug shell.
  - `SO_PEERCRED` logging on `ipc._serve` — every command logs peer
    pid/uid; run `ss -xp`/`lsof` on the socket to identify the ~3 s
    `task_status` poller and the ≤5 ms `choice→interrupt` burst source
    before treating them as bugs.
- **Test scenarios:** click each panel chip/card/stop/label/connect
  against a fake wispd; assert ack → result render; negative cases
  (stale prompt, busy, dropped second command) render an error, not
  silence; suggestion chip resolves via the real `choice` handler.
- **Verification:** full suite green; live repro of "click no on was
  that right" resolves with visible ack; the external emitter is named
  in the unit's handoff notes.

### U2. Unified action lifecycle stream
- **Goal:** one event stream for all actions; confirm card demoted to
  a state in the stream.
- **Files:** `wisp/state.py` (action lifecycle fields),
  `docs/IPC_CONTRACT.md` (contract bump), `shell-plugin/lib/state.js`,
  `WispService.qml`, NowTab/OverlayLayer/StepRow renders.
- **Approach:** `state.actions[]` = `{id, kind, label, status, target,
  reason, undo_ref, at}`; surfaces render the stream; confirm/choice
  publish as `action.status=awaiting` with options attached.
- **Test scenarios:** stream snapshot + diff round-trip in
  `test_state_reader`; a confirm card renders as a stream entry and
  resolves on offer; label/choice/interrupt appear as terminal
  entries.

### U3. Autonomy tier policy
- **Goal:** confirm gates become `policy(tier, session_mode)` instead
  of per-tool bolt-ons.
- **Files:** `wisp/tools/__init__.py` (metadata), `wisp/act.py`
  (`_gate` → policy), `wisp/confirm.py` (batched checkpoint confirm),
  `wisp/settings_schema.py` (autonomy mode setting), tests.
- **Approach:** T0–T3 declared per tool; `act._gate` consults policy;
  session grant mode ("handle X for an hour") held in `state`;
  denylist still preempts.
- **Test scenarios:** T1 tool runs confirm-free; T2 batches at a
  checkpoint and shows the artifact; T3 pauses for handoff; lint test
  fails on an untiered registry entry.

### U4. Conversational agent loop
- **Goal:** `run_act_loop` is a real agent: session turns, goals,
  observe→act→verify, in-loop user questions.
- **Files:** `wisp/act.py`, `wisp/session.py`, `wisp/goals.py`,
  `wisp/stage_execute.py` (route table shrinks: act becomes the default
  for actionable requests), `wisp/stage_route.py` (Jev decides cheaply),
  tests.
- **Approach:** loop carries `messages` across turns (bounded tail +
  summary), a step counter, per-step tool results back into context,
  `ask_user` tool wired to the lifecycle stream, `verify` step after
  mutating actions (screenshot diff or app state), budgets per run.
- **Test scenarios:** multi-step scripted-brain turn completes; a
  mid-loop ask resolves via voice and IPC; a failing tool retries or
  reports; budget/abort renders.

### U5. CUA background delivery + escalation
- **Goal:** per-window/background input before real-pointer; pointer
  yield on real user input.
- **Files:** `wisp/cua.py`, `wisp/tools/system.py`,
  `wisp/cua_safety.py`, `docs/CUA.md`, `wisp/pointer.py`.
- **Approach:** `delivery` field on pointer ops; `background` backends
  (uinput, wtype, CDP Runtime, at-spi where present); pointer ops
  register a real-input listener that cancels on real events; ghost
  cursor unchanged.
- **Test scenarios:** DOM-mode click never moves the pointer; a
  pointer-mode click yields when a real mouse event fires mid-drive;
  blocked desktop-scope ops refuse legibly.

### U6. LLM-aware dictation
- **Goal:** dictate → STT → mode/profile rewrite → insert at cursor.
- **Files:** `wisp/stage_execute.py` (dictation route → mode dispatch),
  new `wisp/dictate.py` (rewrite via brain + profile selection by
  window class), `wisp/tools/system.py` (insert via clipboard-paste
  fallback), `shell-plugin` dictation-mode chip, tests.
- **Approach:** modes `raw|cleanup|compose`; profile table keyed on
  `hyprctl activewindow.class` (terminal → collapse newlines, mail →
  greeting+sig, chat → terse); compose prompt gets app context +
  session tail; insert via wtype-type for short text, clipboard-paste
  for long (WordInk approach), undo = restore clipboard.
- **Test scenarios:** "dictate: hi team" → typed verbatim; compose
  profile → ramble becomes a formatted email; terminal profile strips
  newlines; insert lands in the focused window (fake harness).
- **Dependencies:** U4 (session tail), U3 (insert is T1).

### U7. Adaptive CUA training + Jev verdict
- **Goal:** clicklab/arena generates tasks from observed failures;
  Jev judges outcomes post-run.
- **Files:** `scripts/clicklab/*`, `wisp/judge.py`,
  `wisp/trajectories.py`, `wisp/learn.py`, tests.
- **Approach:** `labels.jsonl` + trace digest feed a failure-mode
  bucket list; `synthesize.py` emits tasks weighted by buckets; Jev
  verdict per run (goal-met?, optimal-path?) lands in labels; recipes
  auto-promote on pass^k.
- **Test scenarios:** synthesized task set skews toward recorded
  failures; verdict lands as a label; a golden-task suite runs in a
  MicroVM fixture.

### U8. Panel/pill presence pass
- **Goal:** the run card surface — intent echo, plan cursor, in-flight
  action, interrupt, mutation summary — on pill + panel.
- **Files:** `shell-plugin/components/*`, `lib/state.js`,
  `WispService.qml`, `lib/copy.js` strings.
- **Approach:** pill shows intent echo + live step; NowTab renders the
  action stream as a checklist; StopControl is always present while
  busy; terminal state shows mutations + undo where available.
- **Test scenarios:** snapshot fixtures for listening/acting/
  awaiting/error states; the card survives daemon restart (file
  fallback).

## Scope Boundaries

**Deferred**
- Clicky-style named personas, routine scheduling UI, and the
  multi-account integration matrix beyond what MCP/strata already
  carries — the agent Spawn/Agents tab surface stays as-is this round.
- macOS/Windows parity — this plan is Omarchy/Linux only; platform
  files keep their seams.
- Full clicklab arena-at-scale beyond the adaptive-coverage addition.

**Outside identity**
- No always-listening mode; screen capture stays on-invocation (the
  privacy stance is a feature).
- No autonomous sends/purchases/credential ops — T3 is human-only by
  design.
- No GPT-6 Astra, no premium model defaults.
- HeyClicky's SaaS proxy tier — wisp stays local-config,
  bring-your-own-endpoint.

## Open Questions

- OQ1. Pointer contention model: exclusive-drive-with-takeover
  (heyclicky's implicit model) vs an agent-scoped Hyprland workspace
  the agent owns? Lean: exclusive-drive-with-instant-takeover, since
  heyclicky proves it works and a scoped workspace can't cover every
  app. Decide inside U5's first PR.
- OQ2. Session-grant shape for T2 ("keep going on this task without
  asking") — per-run card toggle vs a timed grant? Recommend per-run
  "Always approve" matching heyclicky; open until U3 ships.
- OQ3. Dictation trigger surface — dedicated hotkey vs `dictate` verb
  vs a mode toggle in the pill? All three can coexist; pick the
  primary in U6's first PR.
- OQ4. Brain default: is `gemini-2.5-flash` good enough at tool-calling
  for the loop, or does the cheap slot go to a stronger tool-user
  (e.g., `qwen3-32b` class, `gpt-5-mini`)? U4's eval run decides —
  candidate list is part of that unit.

## System-Wide Impact

- `docs/IPC_CONTRACT.md` bumps `contract_version` (action stream) —
  the Rust-parity track (issue #6, U9/W31) must read the new stream
  before freeze.
- `wisp-backend` toggle still flips local↔OpenRouter; loop defaults
  must not pin OpenRouter-only features.
- `wisp/trajectories.py`, `learn.py`, `judge.py` gain a verdict
  source — arena/gauntlet metrics (pass^k, intent-match) keep their
  meanings.
- Settings schema gains `agent.autonomy` and dictation profile keys —
  SettingsTab renders them.
- `wispd label`/`learn`/`suggestion` semantics are unchanged; only
  their UI surface and lifecycle feedback change.

## Risks & Dependencies

- **Confirm fatigue → blanket approve.** Mitigate with tiers, batched
  checkpoints, session grants; launch tiers conservative, loosen on
  evidence.
- **Tier misclassification.** The U3 taxonomy lint + audit is the
  mitigation; a wrongly-T1'd tool is the dangerous case.
- **ASR→action errors.** Intent echo on the run card catches misheard
  requests before the first action; T1 stays strictly reversible.
- **Input race.** Real user input during a pointer-drive run must win
  instantly — U5's listener is the mechanism, verified by an explicit
  test.
- **Model spend.** Per-run step+spend caps with legible abort; all
  eval/arena spend still goes through `orch`.
- **Prompt-injection via screen contents.** Screenshots feed the
  model; a hostile app could inject instructions. Mitigate with a
  content-is-untrusted reminder in the system prompt and the tier
  gate on externally-visible actions (T2/T3 can't be prompt-driven
  into sends).

## Sources & References

- Repo: `wisp/act.py` (existing loop), `wisp/tools/__init__.py`
  (registry+tiers), `wisp/cancel.py` (`PromptBroker`, `CancelToken`),
  `wisp/confirm.py`, `wisp/stage_{capture,route,execute,speak}.py`,
  `wisp/suggest.py`, `shell-plugin/{WispService.qml,lib/state.js,
  components/NowTab.qml,components/OverlayLayer.qml,components/
  SettingsTab.qml}`, `docs/IPC_CONTRACT.md`, `docs/CUA.md`,
  `docs/plans/2026-10-05-001-feat-wisp-full-roadmap-plan.md` (open
  W-IDs), `docs/plans/2026-10-08-001-feat-voice-answers-plan.md`.
- Heyclicky: heyclicky.com (FAQ/changelog), github.com/farzaa/clicky
  (README/AGENTS.md/runtime prompt), deepwiki.com/farzaa/clicky,
  isaacflath.com/writing/how-clicky-works, YC launch notes.
- Dictation: `~/Documents/github/personal/WordInk` (owner's fork,
  `legacy/wordink/text_inserter.py`), github.com/Beingpax/VoiceInk
  (GPL; enhancement layer + Power Mode blueprint).
- Prior plans superseded by this one for direction: proactive-companion
  and dim-* docs are historical; the roadmap plan (W12/W31/W34 open)
  remains the v1.0 gate owner.
