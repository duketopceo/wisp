# Wisp current-state map — clicky/HeyClicky delta baseline

Scope: repo state on branch `feat/capture-pack-verify`. Reference plan:
`docs/plans/2026-10-16-001-feat-heyclicky-teardown-delta-plan.md` (H1-H9).
Feature research: `docs/research/heyclicky-features.md`. REA ledger:
`docs/research/2026-10-16-rea-evidence-and-reconstruction-gate.md` — its rows
claim all H units "Verified (unit)" or "(unit + CI)" against wisp#124; those
claims are unit-test-level only and do not establish runtime wiring.

Status tiers used below: **shipped** = module exists, tested, and called from
the live turn pipeline or daemon; **partial** = module/tests exist but no (or
incomplete) production wiring; **absent** = no implementation.

The live pipeline spine: `wispd` IPC `_dispatch` (wispd:71-369) ->
`pipeline.run_listen` (`wisp/pipeline.py`) -> `stage_capture` -> `stage_route` ->
`stage_execute` (`wisp/stage_execute.py`) -> `act.run_act_loop` (`wisp/act.py`)
-> `stage_speak` (`wisp/stage_speak.py`).

## 1. H1-H9 ship status

| Unit | Module | Status | Production wiring |
|---|---|---|---|
| H1 walkthrough | `wisp/walkthrough.py` | partial | none — no importer outside tests |
| H2 draw-on-screen | `wisp/points.py` (`extract_drawings`) | partial | parser never called in live path; no QML renderer |
| H3 two-stage grounding | `wisp/grounding.py` | partial | chain live; `vlm_point` two-stage provider absent |
| H4 app-keyed skills | `wisp/skills.py` + `wisp/skills_seed/` | partial | library+index wired; `match_app_skill*` never called |
| H5 routines | `wisp/routines.py` | partial | no callers; generated timer targets nonexistent CLI |
| H6 suggest etiquette | `wisp/suggest_policy.py` | partial | pure module; `suggest.py` uses older inline gates |
| H7 conversation grants | `wisp/conversation_grants.py` | partial | production uses `policy.py` session once-grants |
| H8 volatile memory | `wisp/memory.py` (`VOLATILE.md`) | shipped | injected into every answered turn via `context_block()` |
| H9 talk/deep lanes | `wisp/lanes.py` | partial | no callers; equivalent barge-in exists elsewhere |

### H1 — walkthrough state machine — partial

- `wisp/walkthrough.py`: `MAX_STEPS = 15` (:14), `NO_CHANGE_TIMEOUT_S = 20.0`
  (:17), `is_loading_state` (:28-33), `done_log`/`failed_log` (:52-55),
  `diff_window_state` (:122-140), `observe()` consuming Hyprland events +
  window-state diffs (:142-197), `cancel()` emitting `points/clear` +
  `ghost/reset` (:229-232), guide vs. drive modes.
- Its dependencies exist: `hypr.events()` socket2 generator
  (`wisp/hypr.py:482-500`), `Cua.window_state` (`wisp/cua.py:153-155`),
  `verify.verify_action` (`wisp/verify.py`).
- Not wired: grep for `walkthrough` in `wisp/` outside the module -> zero
  hits. No route in `stage_execute.py`/`act.py`; the suggestion RUN path
  calls `act.run_act_loop` directly (`wispd` `_run_suggestion`, wispd:587).
  `hypr.events()` has no other production caller — the socket2 subscription
  exists solely for this unwired module (plus tests).
- Esc-cancel infrastructure exists (`wisp/keys.py` submap -> `fastkey.py`
  interrupt) but is not connected to Walkthrough.
- Net: tested module, never invoked. App-tour UX absent.

### H2 — draw-on-screen overlay — partial (parse-only)

- `wisp/points.py`: `_TAG` regex covers `POINTS|POINT|RING|ARROW|HL` (:121);
  `extract_drawings` (:165-310) parses `[RING:x,y,r]`, `[ARROW:x1,y1,x2,y2]`,
  `[HL:x,y,w,h]` with MAX_DRAWINGS cap, out-of-bounds clamp, and
  mixed-monitor-scale mapping via `_map_drawing_to_logical` (:308);
  `strip_drawing_tags` (:313-315).
- Not wired: `extract_drawings` callers = only `strip_drawing_tags` +
  `tests/test_heyclicky_delta.py`. The live speech path calls
  `points.extract` (POINT/POINTS only) at `wisp/stage_speak.py:144,215,241`.
- No `drawings` field in the state contract — `docs/IPC_CONTRACT.md:91`
  publishes `points` only.
- No `DrawLayer.qml`/`RingLayer`/`ArrowLayer`/`HighlightLayer` under
  `shell-plugin/`; `shell-plugin/components/OverlayLayer.qml` renders only
  ListeningPill, CursorBubble, Beacon repeater, GhostCursor. No
  clear-on-speech-end for drawings.
- User-drawn region capture absent — no slurp/region/scribble input code
  anywhere in `wisp/`.
- What *is* live: `[POINT]`/`[POINTS]` tags -> state `points` ->
  `shell-plugin/components/Beacon.qml` numbered pins (~8 s hold->fade);
  `cua.target` bus events -> `shell-plugin/components/GhostCursor.qml`
  (travel/click/park/return + breadcrumbs + "not sure" label).

### H3 — two-stage element grounding — partial

- Ported clicky math: `POINTING_RESOLUTIONS` (grounding.py:139-148),
  `pick_pointing_resolution` (:152-169),
  `scale_point_from_resolution` (:176-199) — oracle-tested against literal
  Swift translations in `tests/test_heyclicky_delta.py:35-77`.
- Live provider chain `control -> a11y -> uitars -> jev`
  (`grounding.py:709-714`, default `[ground] providers` at
  `wisp/config.py:152`); `ground_target` re-observes once below
  `min_confidence` (0.5) then raises `GroundRefused` (:736-753) — never
  clicks low-confidence targets.
- The plan's `vlm_point` two-stage provider is absent: grounding.py:27-28
  docstring states it "is NOT shipped"; no `[ground] point_model` config;
  no describe-then-point call.
- Net: coordinate-space half shipped+tested; the detection->confirmation
  two-stage half absent. The live chain is fallback-on-failure, not
  clicky's two-stage.

### H4 — app-keyed skill library — partial

- `wisp/skills.py`: frontmatter `meta()` (:87-124); keyword-ranked
  `index_text` injection (:186-234); `register_tools` -> `skill_<name>`
  bash tools with tier floor (:240-290); `seed()` (:297-307);
  `import_dir` community-dir import (:313-343); `match_app_skill` /
  `match_app_skill_info` (:398-485) with `url_hosts` > `app_classes`
  precedence (:460-466).
- Seeds: `wisp/skills_seed/` = 15 app-keyed (`apps/chromium`,
  `apps/firefox`, `apps/gimp`, `apps/github`, `apps/hyprland`,
  `apps/kitty`, `apps/libreoffice`, `apps/nautilus`, `apps/neovim`,
  `apps/obsidian`, `apps/spotify`, `apps/steam`, `apps/thunderbird`,
  `apps/vsode`, `apps/whatsapp`) + 5 unkeyed (`browseros`,
  `dayflow-bridge`, `filmcraft`, `self-checkup`, `wispd`).
- Wired: `skills.register_tools()`/`seed()`/`write_index_json()` at daemon
  start (`wispd:652-655`); `index_text` into context via
  `memory.context_block()` (`wisp/memory.py:493-502`) called by
  `wisp/stage_speak.py:58` and `wisp/stage_capture.py:445`; `skill_manage`/
  `skill_view` tools (`wisp/tools/__init__.py`); `wispd skills *` CLI
  (`wisp/cli/learning.py`).
- Unwired: `match_app_skill*` — no production caller; the focused app's
  skill body is never auto-injected. No `wispd skills match` CLI.

### H5 — routines — partial

- `wisp/routines.py`: `Routine`/`RoutineStore` JSON (:76-165);
  `generate_systemd_units` emits `.service` + `.timer` with
  `Persistent=true` (:168-195); `require_first_opt_ingate` (:203-216);
  `record_routine_outcome` (:219-251) — 3 consecutive failures auto-pause,
  quiet success sets `unread` instead of speaking, failure announces once.
- Not wired: generated `ExecStart` calls `wispd agents run <id>` — no
  `agents` command group exists in `wisp/cli/`, and the daemon `_dispatch`
  (wispd:71-369) has only `agent`/`task_status`/`task_cancel`. No
  `wispd routines` CLI; `RoutineStore`/`record_routine_outcome`/
  `require_first_opt_ingate` have zero production callers;
  `shell-plugin/components/AgentsTab.qml` (33 lines) renders no unread
  indicator.
- Net: a complete tested library with no create/schedule/report path —
  generated timers would fire a nonexistent command.

### H6 — suggestion etiquette policy — partial

- `wisp/suggest_policy.py`: `evaluate_suggestion_etiquette` (:37-94) —
  earliest-hour gate (default 6 am), hold on call/screen-share/fullscreen,
  dismissal-streak backoff (3 consecutive dismissed days -> 7-day pause),
  paused-until check; `declined_reasons_prompt` (:99-114).
- Not wired: `suggest.py` never imports it; `mine()`/`run()` gate on
  `[sense]`/`[suggest]` config and their own dismissal handling. No
  `suggest_policy` reference outside tests.
- Prerequisite missing: `sense.py` snapshot carries active window +
  dayflow tail only — no PipeWire call, camera/mic, or fullscreen
  detection to feed the policy.
- Net: policy engine shipped+tested; live suggest loop uses older inline
  gates without call/fullscreen awareness.

### H7 — per-conversation permission grants — partial

- `wisp/conversation_grants.py`: `GrantScope` (:14-21), `HARD_STOP_KINDS`
  `purchase/send/delete/payment` (:25-29), `ConversationGrantManager`
  `allow_once`/`always`/`not_now` + audit (:34-120),
  `parse_voice_grant_reply` (:123-149).
- Live path uses a different model: `wisp/policy.py` confirm-once session
  grants keyed `(tool, app)` + `ALWAYS_GRANT` admin mode; `wisp/confirm.py`
  yes/no/always cards over `cancel.PromptBroker`; voice answers via
  `wisp/voicepick.py` + mini-capture `_voice_answer` (`wispd:446-503`).
- `conversation_grants` imported only by tests; no `conversation_id`
  plumbed into dispatch/policy checks.
- Net: scoped manager exists as a library; production keeps session-scoped
  `(tool, app)` grants.

### H8 — volatile memory — shipped

- `wisp/memory.py`: `VOLATILE.md` layer — `VOLATILE_BUDGET` ~1600 chars,
  `VOLATILE_MAX_LINES` 40, `VOLATILE_TTL_DAYS` 7 (:36-41); entries carry
  `until: YYYY-MM-DD`, expire on load; `append_volatile` (:364-400);
  `volatile_snapshot` (:403-405); `promote` volatile -> MEMORY.md
  (:434-441).
- Wired: `volatile_snapshot()` inside `context_block()` (memory.py:491),
  called by `wisp/stage_speak.py:58` and `wisp/stage_capture.py:445`;
  `memory` tool target `volatile` + `promote` op reachable via tool
  grammar and `wispd memory` IPC (`wispd:285-292`).
- The only H unit live end-to-end.

### H9 — talk/deep lanes — partial

- `wisp/lanes.py`: `LANES` talk/deep `LaneConfig` (:14-26),
  `select_lane` heuristics (:38-64), `LaneLedger` JSONL (:66-95),
  `BargeInController` cancels TTS proc + token stream (:99-141).
- Functionally equivalent pieces exist elsewhere: `wisp/brain.py`
  `[brain] first_token_s` default 3 s + `chat`/`chat_stream` +
  `supports_vision`/`supports_tools` (:114-135, :376-393); barge-in
  already implemented in the daemon (new press -> `speech.stop()` +
  `CancelToken`, `wispd:185-186`, `_interrupt`/`_spoken_stop` :506-524).
- Not wired: `lanes` imported only by tests; no lane field in
  `stage_route` choices; single `answer_model`/`agent.model` config, no
  per-lane models; `LaneLedger` unused (`wisp/ledger.py` is spend, a
  different ledger).
- Net: machinery+tests shipped; no lane split at runtime.

## 2. Subsystem inventory and integration surface

### Daemon / IPC
- `wispd` `_dispatch` (wispd:71-369): cmds `status`, `listen`,
  `choice`, `suggestions`, `task_status`, `task_cancel`, `agent`,
  `memory`, `dictate_correct`, `label`, `learn`, `harness`, `config`,
  `interrupt`, `context`, `captures`, `stop`. Mini-capture path
  (`_voice_answer`, :446-503) voice-answers pending prompts or spoken
  stops without starting a new turn. `run_daemon` (:650-745): skills
  register/seed/index, theme emit, memory sync, inventory scan, orphan
  rec sweep, packs maintenance, spend ledger, health registry, agents
  reaper, keys submap, sense+suggest threads.
- `wisp/ipc.py`: NDJSON over AF_UNIX (TCP on Windows), `subscribe` push
  topics; peer-cred attribution for `captures`.
- Contract: `docs/IPC_CONTRACT.md` — state fields include `points`,
  `guide`, `goal`, `focus`; no `drawings`, no walkthrough/guide-step
  surface.

### Background agents — `wisp/agents.py`
- `spawn` -> detached `Popen` of an external CLI runtime
  (`[brain] agent_runtime`; `AGENT_RUNTIMES` = ori opencode / codex /
  claude / devin); task records in `tasks.jsonl`; per-task log file.
- Liveness via `/proc/<pid>/stat` field-22 process-start match
  (:104-136); `tasks()` snapshot prunes stale rows.
- `start_reaper`/`_tick_events` (:324-449): poll -> SIGTERM -> grace ->
  SIGKILL the process group; `[agent] task_timeout_s` reap; finished
  events -> `wispd` `_agent_done` -> `notify_tool` toast (wispd:708-713).
- Agents are opaque subprocesses: no in-process tool access, no output
  file artifacts surfaced, no delivery verification, no scheduling, no
  quiet/unread landing.

### Voice / audio
- STT `stage_capture.transcribe` (`wisp/stage_capture.py:74-169`): local
  whisper.cpp binary (`WHISPER_BIN` + model + prompt file, batch file->
  text, not streaming); `[stt] provider` `openai` = Groq-compatible
  `/audio/transcriptions`; `wordink` = local gateway module.
  `wisp/vocab.py` builds the dynamic whisper prompt (skills, memory
  proper nouns, recent window titles; 1 h cache).
- TTS `wisp/speech.py`: `speak`/`speak_cmd` spawn `platform.tts_argv()`
  or `[voice] cmd` per call; `SentenceSpeaker` speaks sentence chunks
  while the answer streams; `stop()` kills the proc group + fifo —
  wired to barge-in on new press / `interrupt` cmd / spoken stop.
- `wisp/dictate.py`: modes `raw`/`cleanup`/`compose`; per-app profiles
  (terminal -> paste not enter); personal corrections in
  `dictation.json` via `wispd dictate correct` IPC (`wispd:293-306`)
  and the "heard -> meant" voice form (`_maybe_correction`,
  dictate.py:403-409). No timed post-insert auto-learn window.
- `wisp/fastkey.py`: stdlib-only low-latency IPC client for the key
  submap; `wisp/keys.py` Esc/Enter/1-9 binds while `acting`/
  `awaiting_choice`.
- `wisp/voicepick.py`: spoken-answer -> option index mapping; `is_stop`.

### Skills — `wisp/skills.py` + `wisp/skills_seed/` (see H4)

### Memory
- `wisp/memory.py`: durable `MEMORY.md` (~800-token block) + `USER.md`
  (~500) + `VOLATILE.md` decaying layer; `context_block()` injects all
  three + skills index; `memory` tool target/op grammar; `wispd memory`
  IPC + `wispd memory` CLI; `sync_constitution` luke-agents import.
- `wisp/session.py`: append-only `session.jsonl` turn log; `tail()`
  feeds "Recent conversation" system message (`stage_speak.py:61-63`).
- `wisp/recall.py`: `recall.db` SQLite FTS5, ~5000-note cap, optional
  sqlite-vec embeddings; `index_turn` off the hot path via `bgwriter`
  (`stage_speak.py:284`).
- `wisp/goals.py`: one open goal, `join_or_new` on same-app or topic
  overlap, `[agent] goal_ttl_s` default 600; `context_text` into act
  prompt — Wisp's multi-utterance continuation mechanism.
- `wisp/trajectories.py`: per-act-run episodic JSONL; similar prior
  runs injected; `propose_recipes` -> `recipe-*` skills via human-gated
  approve (`wispd recipes`).

### Integrations
- MCP OAuth: `wisp/mcpauth.py` — `wispd connect list/add`
  (`wisp/cli/settings.py:149-169`) through the BrowserOS Klavis Strata
  gateway (~45 services); tokens in
  `~/.local/state/browseros/mcp-tokens.json`.
- MCP client: `wisp/tools/mcpclient.py` — `mcp_call` tool; `connect`
  gateway or direct `url`; http + stdio transports; strata path routes
  through `execute_action`; stdio sessions kept alive across calls.
- App control channels: `wisp/control.py` — `AppControlRegistry` from
  `[control]`/`[control.<app>]` config plus built-in FilmCraft
  127.0.0.1:9876 (:386-389, :456-470); methods `ui.elements`,
  `ui.inspect`, `ui.screenshot`, `ui.state`; registers the "control"
  verify rung at import (:865-876); loopback-only, rect-in-window
  validation.
- Tool registry: `wisp/tools/__init__.py` — `REGISTRY` 4-tuples (fn,
  tier, desc, autonomy meta); `EXTERN` vs in-loop tools; `LOOP_ONLY`
  ask_user; `tool_schemas` for OpenAI-style function calling.
  `wisp/policy.py` T0-T3 autonomy tiers + session once-grants;
  `wisp/confirm.py` cards via PromptBroker.
- Hyprland: `wisp/hypr.py` socket1 request/eval batch + socket2
  `events()` (:482-500) — latter only consumed by unwired walkthrough.
- CUA: `wisp/cua.py` `cua-driver` CLI argv client, `SESSION="wisp"`,
  typed `click`/`move_cursor`/`window_state`/`list_windows`.

### Pointing / overlay / input delivery
- `wisp/points.py`: tag parse + screenshot-px -> logical monitor mapping
  (`to_logical`, `canvas_to_logical`).
- `wisp/grounding.py`: provider chain + `emit_target` `cua.target`
  events.
- `wisp/pointer.py`: backend registry `cua > hyprcursor > ydotool >
  wlrctl > guide` (:43); click never retried on another backend; move
  falls through; `Outcome.delivery` per call.
- `wisp/delivery.py`: `auto`/`background`/`pointer` policy
  (`[cua] delivery`, config.py:134-143) + per-call delivery stamp.
- `wisp/realinput.py`: yield watch — evdev direct or cursor-drift poll;
  arms only after a real-pointer dispatch; physical input wins ->
  `cancel.Cancelled`.
- QML: `Beacon.qml` numbered pins; `GhostCursor.qml` bezier travel,
  click ripple, parked label, return, breadcrumbs, unsure state;
  `OverlayLayer.qml` wires pill/bubble/beacons/ghost; lib JS helpers
  (`cursor.js`, `copy.js`, `steps.js`, `metrics.js`) for positioning
  and copy strings. No drawing layer; no user-input overlay surface.

### Verification / capture
- `wisp/verify.py`: cheap-first ladder — masked pixel diffs, registered
  rungs (`control`), vision judge on ambiguity; unknown never promotes
  to `landed`; `unverifiable` preserved.
- `wisp/record.py`: cua `start_recording` into `rec/<turn>/turn-NNNNN/`
  (0700), session TTL renewal, tool+args+ts attribution.
- `wisp/observe.py`: model-facing frame capture (control `ui.screenshot`
  or cua zoom) into `turn-9NNNN/` pack-linked dirs; deny-surface
  suppression before capture.
- `wisp/packs.py`: `packs/<turn>/` manifest + frames + contact sheet;
  redaction; `captures_response` for the `captures` IPC; retention
  `maintenance`.
- `wisp/learn.py`/`wisp/train.py`/`wisp/review.py`: labeled corrections,
  arena, reviewer proposals — human-gated learning loop.

## 3. Gaps vs clicky/clacky (factual)

1. Persistent conversation / follow-ups — partial. `session.jsonl`
   tail + `goals.py` 600 s goal continuation + mini-capture voice
   answers exist; no deep transcript memory (~40-message equivalent)
   feeding the model beyond the session tail.
2. App tours — absent at runtime (H1 library only; no trigger, route,
   or UI affordance).
3. Voice-taught routines — absent. No voice path creates a `Routine`;
   suggestion cards run one-off act loops; the scheduling half is
   unwired and its `ExecStart` targets a nonexistent `wispd agents run`
   command.
4. Background agents that deliver files — absent. `agents.py` is
   text-in/text-out; no artifact surfacing, drag-out, or delivery
   verification.
5. MCP connector surface — present. `connect` OAuth + `mcp_call`
   (http/stdio/strata). Missing vs clicky: multi-account labeling and
   a paste-URL-and-key flow for arbitrary MCP servers (only the
   Strata catalog is first-class).
6. Reversible file operations — absent. No file read/write/move tools
   exist in `REGISTRY`; only denylist-guarded `shell`.
7. Element-snap pointing — absent. Beacons/ghost point at coordinates;
   `Target.element_rect` exists in grounding but nothing renders or
   interacts with snapped element bounds.
8. Draw-on-screen — parser only; no QML renderer, no state field, no
   user-drawn region capture.
9. Named persistent agents with persona/memory/files folder — absent;
   `tasks.jsonl` rows are ephemeral process records.
10. Agent-finish announcements — partial. Finish -> desktop
    notification toast (`_agent_done`, wispd:708-713); no spoken
    announcement, no call/DND gating.
11. Call / screen-share / fullscreen awareness — absent. `sense.py`
    snapshot lacks PipeWire/camera/mic/fullscreen detection; blocks
    H6's hold conditions too.
12. Talk/deep model lanes — partial. Brain supports entry chains and
    a first-token budget, but a single `answer_model`/`agent.model`
    pair is used; `lanes.py` is dormant.
13. Per-conversation grant scoping — partial. Session-scoped
    `(tool, app)` once-grants live in `policy.py`; the H7 conversation-
    scoped manager is unused.

## 4. Notable evidence notes

- `docs/research/2026-10-16-rea-evidence-and-reconstruction-gate.md:36-47`
  marks H1-H9 verified at unit level — consistent with this map's
  partial ratings (module+tests != wired).
- `hypr.events()` socket2 subscriber exists solely for the unwired
  walkthrough (plus test fakes).
- `wispd` `captures` IPC is peer-cred-gated and read-only; `--full`
  required for transcript/state-dump text.
- No PR lifecycle beyond what `docs/` text asserts was verified here.
