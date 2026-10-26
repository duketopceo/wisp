# Clacky — source-assisted teardown (for wisp adoption review)

Repo: /tmp/clacky-src (github.com/Raynan00/clacky, v0.2.0)
License: **MIT** (`LICENSE`, copyright Raynan Wuyep 2026; pyproject.toml:7).
Vendored base is `Bitshank-2338/clicky-windows` (MIT, notice kept at
`clacky/shell/LICENSE.bitshank`, provenance in `clacky/shell/VENDORED.md`).
Copying patterns/ideas: fully compatible; keep attribution for lifted code.

## Repo shape

Two products in one tree:

- `clacky/` — the CLI package (`clacky organize|undo|run|connect`, cli.py).
  - `clacky/agent/` — trust-layer core: `permission.py` (4-tier Risk),
    `fileops.py`/`journal.py`/`planner.py`/`runtime.py` (organize engine),
    `actuation.py` (Actuator ABC + pynput WindowsActuator + RecordingActuator),
    `computer_loop.py` and `narrator.py` (**scaffolds, not wired live**).
  - `clacky/providers/` — organizer LLM providers behind `complete(system,user)`:
    claude/openai/gemini/ollama/heuristic (`providers/factory.py`,
    `providers/base.py:12`).
  - `clacky/connections.py` + `clacky/oauth.py` — MCP wiring + OAuth flow.
- `clacky/shell/` — the PyQt6 voice companion, vendored then extended.
  Entry `shell/main.py` (380 lines: boot Qt, wire ~20 pyqtSignals, hotkeys).
  Brain = `CompanionManager(RoutingMixin, TourMixin, ActionsMixin, QObject)`
  in `shell/companion_manager.py` (~1600 lines) + `shell/routing.py`,
  `shell/tour.py`, `shell/actions.py`. Added on top of the vendor base:
  `harness.py`, `acp_client.py`, `agent_skills.py`, `memory_store.py`,
  `session_log.py`, `audio/stt/deepgram_streaming.py`, `ui/connect_dialog.py`.
- `organizer/` — dead prototype superseded by `clacky/agent/` (kept for tests).
- `skills/` — repo-level community skills + legacy python-skill example.
- `tests/test_clacky_core.py` — 8 tests, headless, FakeProvider; covers
  fileops guards, planner validation, execute→journal→undo roundtrip, dry-run.
  **Shell has zero automated tests** (CI: `.github/workflows/tests.yml` runs
  pytest + py_compile import-safety only; CONTRIBUTING.md:43-45 admits it).

Deps: `pyproject.toml` — core has zero deps; extras `claude|openai|gemini|
google|background|dev|shell`. `[shell]` pulls PyQt6, mss, Pillow, keyboard,
sounddevice/soundfile/numpy/av, faster-whisper, edge-tts, httpx/aiohttp,
ollama, uiautomation (UIA pointing), pynput (actuation), hermes-agent + ddgs +
agent-client-protocol (bg lane, py<3.14 only). `shell/requirements.txt` lists
optional extras (elevenlabs, pypdf, pytesseract, langdetect, imageio-ffmpeg).

Architecture notes: asyncio loop on a daemon thread, all UI updates via
pyqtSignals (`companion_manager.py:266-283`, `main.py:86-125`). Sleep/wake
watchdog: monotonic heartbeat drift >15s => restart mic+loop
(`companion_manager.py:456-495`).

## 1. Pointing / element snap — HIGH confidence

Three independent resolvers + a snap layer; the "buddy" itself never knows
which produced a coordinate.

- **Tier 1 UIA** (`shell/ai/hybrid_pointer.py:125-198`): `uiautomation`
  `GetForegroundControl()` (falls back to root), BFS bounded at 3500 nodes /
  depth 40. `_score_match` (87-122): normalizes, strips generic UI nouns
  ("button", "field", "the"...), scores both directions (query-in-name,
  name-in-query), word-overlap ratio for multi-word, +0.12 bonus for
  `_CLICKABLE_TYPES`, +0.05 other interactive. Also tries AutomationId at 0.8x
  and HelpText. Returns `Target(x,y,bbox,label,source="uia",confidence)`.
  ~5ms, pixel-perfect; center of BoundingRectangle.
- **Tier 2 OCR** (same file, 223-287): RapidOCR/ONNX on the primary screen —
  for canvas apps (Figma/games) where UIA is sparse. Detections conf>=0.4,
  same `_score_match`, bbox->center.
- **Tier 3** delegates to the caller; two paths in
  `companion_manager.py:945-1004`:
  - `ai/element_locator.py` — Claude **Computer Use as a locator**: screenshot
    resized to nearest of (1024x768, 1280x800, 1366x768) by aspect ratio
    (`_pick_resolution`, :52-61); one message with `computer_20251124` tool
    asking "click on that element"; first `tool_use` coordinate mapped
    CU-space -> physical px -> +monitor origin -> /dpi_scale -> logical Qt px
    (:163-189). Beta header `computer-use-2025-11-24` (:31). Shared warm httpx
    client, reset on error.
  - `ai/universal_locator.py` — Set-of-Mark for any vision LLM: stage-1 12x8
    numbered grid drawn on the shot -> `{"cell": n}` JSON (tolerant parser:
    JSON first, then first in-range integer, :146-174); stage-2 crops a 3x3
    cell region, upscales >=768px, 6x6 sub-grid -> sub-cell center -> same
    coordinate transform. ~25-50px; falls back to stage-1 cell center.
- **Nudge-snap** (`tour.py:54-83`): `ControlFromPoint` at the model's physical
  coord; only snaps to controls <=600x360 whose center is <=30px away —
  *container guard* so it never jumps to a big panel/window.
- **Label-first snap**: `[POINT:x,y:label:screenN]` tags from the chat path are
  resolved by `find_target(label, skip_ocr=True, skip_vision=True)` (UIA only,
  ~5ms); only on miss does it trust the model's coordinate
  (`tour.py:104-144`). Dedup by label per turn.
- **One held point**: `detected` hits are stored as `self._main_point` and
  `_suppress_llm_point=True` — they fire only once speech starts
  (`_fire_main_point`, `tour.py:38-52`), so the cursor never points before
  talking; LLM-emitted points can't override the accurate detection.
- Coordinate discipline lives in `screen/capture.py`: ScreenShot carries
  downscaled w/h + physical w/h/origin + dpi_scale + logical origin — three
  spaces kept straight (docstring :1-16).

## 2. Brain loop — HIGH confidence

Two things share the "brain" name:

**A. Live act loop** — `shell/actions.py::_run_task` (683-897), raw httpx
(no SDK) POST api.anthropic.com, model `claude-sonnet-5`, beta header
`computer-use-2025-11-24`.
- Tools (:787-810): `computer` (`computer_20251124`, display=tw x th),
  `launch_app` (exe paths/URL protocols/`start`, `_APP_LAUNCHERS` map +
  user `~/.clacky/apps.json` overrides, :577-655), `open_url` (known web-app
  map gmail/calendar/... -> logged-in browser session, `_WEB_APPS` :660-670).
- Cadence: each turn posts messages; executes all tool_use blocks; sleeps
  0.8s (1.8s after open_url); re-screenshot; each tool_use gets a tool_result
  containing the fresh image (:868-889). `MAX_STEPS = 12` (:821).
- Verification = the model seeing the next screenshot; nothing mechanical.
- Conversation threading: messages list grows in-loop; chat replies use
  per-app history `_app_memory[app_key(window_title)]` capped at 20
  (`companion_manager.py:1079-1082`).
- Narration: model is told to include a 2-4-word action note -> `_action_label`
  (530-550) shown as a cursor pill via `sig_point_at` on every coordinate
  action; speaks ONLY one <=15-word closing line (`say()` caps at whole-
  sentence boundary, :729-749).
- Safety in prompt (:751-775): "do NOT send, delete, buy, post, or pay...
  unless the task explicitly asks... do everything up to that step, then STOP
  with a closing line and NO tool call." Plus `_cancel_flag` (Esc/barge-in)
  and `sig_point_release` in `finally`.

**B. Scaffold layer** (`clacky/agent/computer_loop.py`, `narrator.py`) —
designed but `ComputerAgent.run` raises NotImplementedError (:137). The
Narrator dataclass (`computer_loop.py:57-67`) and `run_narration`'s
point/say/finish tool loop (`narrator.py:89-151`) show the intended
injectable-fakes pattern; not wired in the shell (no callers found).

**C. Chat brain** — `stream_response` providers (`ai/claude_provider.py:17-55`
etc.), streaming text + screenshots; the big prompt is `_build_system_prompt`
(`companion_manager.py:96-204`): SOUL.md persona + ctx lines (date, active
window, DETECTED ELEMENT, lesson progress) + mechanics block ([POINT]/
annotation tag grammar, "never say screenshot/coordinates", web-search
citation rule, public-figures anti-refusal rule) + optional OCR/doc/memory/
bg-tasks blocks. Quiz mode replaces the whole prompt (:124-146).

**Routing** — `shell/routing.py`: `_fast_route` (51-112) conservative local
regexes for unambiguous cases (explicit "go/agent/do it" trigger FORCES act;
organize; walkthrough; plain factual -> chat); everything else -> `_route`
(114-196): one Haiku call, forced `route` tool, enum
act|walkthrough|remember|forget|learn_skill|background|workspace|organize|
undo|chat, with skill names injected into the system prompt and a
`workspace` route only when google_workspace is configured. Design
philosophy in the docstring: **the model is the routing authority; regexes
are latency shortcuts** — the inverse of naive keyword routing.

## 3. Voice pipeline — HIGH confidence

- **AmbientListener** (`shell/audio/ambient_listener.py`): one sounddevice
  stream, 16kHz/mono/int16/30ms blocks, RMS levels always emitted. STANDBY:
  energy VAD (0.006 RMS, 3 blocks to open, 20 blocks/600ms silence to close,
  3.6s cap) with a 540ms pre-roll ring buffer -> segment -> faster-whisper
  tiny.en int8 CPU (padded 400ms each side, `initial_prompt` naming the app)
  -> substring match vs ~20 coined-name variants (`WAKE_WORDS` :38-44 —
  covers "clacky/clackie/klacky/cracky/hey clack"...). RECORDING: buffers PCM
  + optional per-chunk sink for live STT (`set_rec_chunk_callback`).
- **Deepgram streaming** (`audio/stt/deepgram_streaming.py`): wss nova-3,
  linear16/16k, `interim_results=true&endpointing=300&smart_format&punctuate`,
  `&keyterm=` boosting for "Clacky" + `CLACKY_STT_KEYTERMS` (:36-45). Only
  `is_final` transcripts accumulate (:98-101); `finish()` sends Finalize,
  waits 0.4s grace, CloseStream (:105-128). Push-to-talk means no silence-
  detection wait — transcript is ready ~instantly on release. Default ON
  (`CLACKY_STREAM_STT`!=0) when deepgram key present; batch PCM always kept as
  fallback (`companion_manager.py:650-675, 750-761`).
- **Batch STT**: `deepgram_stt.py` (POST wav -> nova-3), `faster_whisper_stt.py`
  (small.en default, cpu/int8), `whisper_cpp_stt.py` (pywhispercpp, GPU),
  `openai_stt.py`.
- **TTS**: `edge_tts_provider.py` — free Edge neural voice (AvaNeural),
  `synth()`->mp3 bytes separate from `speak()` so callers can time playback.
  ElevenLabs/OpenAI providers exist (`cfg.tts_provider()` priority:
  elevenlabs->openai->edge, `config.py:172-177`).
- **Gapless streaming TTS** (`companion_manager.py:1090-1141`): while the LLM
  streams, display text is cleaned of tags; `_split_complete_sentences`
  (:1311-1324) splits ONLY on `[.!?...]` followed by whitespace (never end-of-
  buffer -> "3.5" across chunks isn't chopped); each completed sentence is
  synthesized immediately (`synth` ahead) into `_audio_q` drained by one
  ordered player task — next sentence synthesizes while current plays.
  `CLACKY_STREAM_TTS=0` reverts to whole-reply.
- **Barge-in**: hotkey press during THINKING/SPEAKING sets `_cancel_flag` +
  `stop_audio()` (module-level `threading.Event`; chunked 50ms playback loop
  polls it -> ~50ms kill, `playback.py:24-31,64-95`) then starts a new
  capture (:564-577). `_gen` generation counter prevents the cancelled
  turn's `finally` resetting state over the new turn (:604-606, :1254-1256).
  Esc -> `StopHotkey` -> `manager.stop()` (:1586-1605).
- **Latency engineering**: `_prewarm_screenshot` on key-down (8s staleness
  TTL, :677-690); `_warm_up` (:381-426) pre-inits providers, does a throwaway
  TTS synth, pre-bakes ack clips ("Let me take a look."), warms the shared
  httpx pool + a 1-token Haiku call; instant ack plays the moment a slow
  route is chosen (:848-852); optional `CLACKY_FILLER` thinking clips
  (:613-648). Wake-word auto-stop: 10s max, no silence-endpointing
  (`_auto_stop_after_pause` :692-701).

## 4. Memory + routines — HIGH confidence

- `shell/memory_store.py`: `~/.clacky/memory.json`
  `{facts:[{text,ts}], skills:{name:{steps,ts}}}`.
  `facts_block()` (:88-94) injected into every system prompt — passive
  recall, no retrieval step; case-insensitive dedupe; bounded at 100.
  `forget()` substring match; "everything/all" wipes (:74-86).
- Voice-taught routines: router emits `learn_skill` + `skill_name` +
  `skill_steps` -> `agent_skills.save_skill` writes
  `~/.clacky/skills/<slug>/SKILL.md` (agentskills.io frontmatter
  name/description + body, `agent_skills.py:44-66`) and mirrors into legacy
  JSON. `migrate_legacy` lifts old JSON routines once (:120-132).
- Recall: progressive disclosure — `names_block()` (names+descriptions only)
  always in the act prompt; FULL body injected only when `find()` matches
  (longest-name substring in utterance, :100-108) — in both the foreground
  act loop (`actions.py:778-786`) and the bg harness prompt
  (`harness.py:82-91`).
- Per-app session memory: `_app_memory[app_key]` 20-message cap
  (`companion_manager.py:303, 1080-1082`) — context doesn't bleed between
  apps.
- `tutor_features/journal.py`: SQLite Q&A log (`%LOCALAPPDATA%\Clacky\
  journal.db`) with SM-2-lite spaced repetition (intervals 1,3,7,14,30,60,120d;
  `next_review_at`,`streak`); voice queries today/week/"quiz me".

## 5. Skills — HIGH confidence (TWO systems, don't conflate)

- **SKILL.md skills** (`shell/agent_skills.py`): folders
  `~/.clacky/skills/<slug>/SKILL.md`, YAML-ish frontmatter + markdown body.
  Load per-turn (cheap glob), `find()` = longest-name substring match.
  Consumers: router (name list -> act), act loop (full body on invoke),
  harness prompt (same). No app/site matching — unlike openclicky's
  suggestion-rules.json (referenced in docs/SCOPE.md:49 but not built).
- **Python trigger skills** (`shell/skills/__init__.py`): `.py` files exposing
  `SKILL={name, trigger-regex, description, handler(manager,transcript)}`,
  loaded from package + `~/.clacky/skills/*.py`, matched BEFORE the LLM like
  built-in commands (`companion_manager.py:824-833`). Example:
  `example_self_mode.py` (arms click-through).
- `skills/organize_desktop.py` + `skills/organize-desktop.md` — older
  prototypes of the two styles at repo root.

## 6. Background agents — HIGH confidence (the richest subsystem)

`shell/harness.py` + `shell/acp_client.py` + `shell/actions.py:237-529`.

- Backend: `hermes-agent` (Nous Research, MIT) on the user's same Anthropic
  key; detection = `shutil.which("hermes")` (:54-62). Per-task workspace
  `~/.clacky/background/<ts>-<slug>` (:65-70).
- ACP session (`acp_client.py`): spawns `hermes acp --accept-hooks`, newline
  JSON-RPC over stdio: initialize (fs clientCapabilities false) -> session/new
  with `mcpServers` built from hermes config (:50-72) -> session/prompt.
  Auto-approves `session/request_permission` picking the first option with
  "allow" in id/kind (:131-140). **Answer extraction**: text chunks after the
  LAST tool_call — earlier text is "thinking out loud" and must never reach
  the ear (:115-120, 166-168). `tool_evidence` = raw tool_call JSON lines.
  `-z` one-shot is fallback (no MCP there, :230-245).
- Prompt contract (`harness.py:82-131`): "You are Clacky's background worker"
  + task + optional matched skill body + screen-context + connected-apps
  block + file-output contract ("save outputs as files inside {ws}, prefer
  one markdown file") + spoken-summary contract (2-3 sentences, past tense,
  no paths/markdown) + `LINK: <url>` final line for delivered URLs.
- **"Never claims a delivery she didn't make"**: LINK: lines kept only if the
  URL appears verbatim in `tool_evidence` — i.e., a real tool result returned
  it; model prose (possibly prompt-injected by a web page) can't open
  anything (:194-201). Foreground then `webbrowser.open`s it.
- **Deferred auth handshake**: prompt tells the agent that if a Composio app
  needs auth, write the auth link to `CONNECT-<app>.txt`, still save outputs,
  end turn, never wait (:95-104). Foreground `_pending_auth` finds the file
  (`actions.py:381-395`), opens the browser ONLY if host is composio.dev /
  *.composio.dev (allowlist — the file was written by a web-browsing agent,
  :288-307), then `_finish_delivery` re-runs the task in the same workspace
  at 75s/150s with a "files are already there, do ONLY the delivery, delete
  the CONNECT file on success" prompt (:397-426).
- Deixis: `_DEIXIS_RE` ("this/what I'm looking at/on my screen") triggers one
  Haiku vision call describing the focused window (window-title anchor) —
  the blind lane's eyes via translation (`actions.py:334-379`).
- Pre-flight: `_missing_delivery_app` — 20-token Haiku check vs live
  connected list -> `ConnectDialog` offer, never a gate (:428-480).
- Secrets: `_KEEP_PRIVATE` env scrub (Deepgram/OpenAI/Google/ElevenLabs/
  Tavily keys + VS Code IPC tokens) — bg agent gets ANTHROPIC key but nothing
  a prompt-injected page could exfiltrate usefully (:37-42, :163-165).
- Ops: `CLACKY_BG_MODEL` (default claude-sonnet-5), `CLACKY_BG_TIMEOUT`
  (default 900s; on timeout salvages existing files, :180-186);
  `refresh_stale()` renews OAuth before each run (:149-153); `_bg_report`
  waits up to ~3min for IDLE before speaking (:513-519); `_bg_block` lists
  running tasks into the chat prompt (:521-528).
- Hermes config interop (`connections.py:105-146`): remote servers get
  `connect_timeout:60, timeout:180`; `mcp_discovery_timeout` forced >=30
  (hermes default 1.5s loses the race for remote MCP mounting); server name
  appended to `platform_toolsets.cli` (one-shot toolset allowlist).
- Fallback when no hermes: `_research_agent` — Sonnet + `web_search_20250305`
  tool (max_uses 5, handles `pause_turn`), 4-turn cap, spoken summary
  (:482-511) + one-time "install the real engine" upsell (:319-324).

## 7. MCP / Composio connectors — HIGH confidence

- `clacky connect [name] [--url|--command|--token]` (`cli.py:89-145`): name ->
  `KNOWN_APPS` registry (notion/linear/sentry/github/huggingface/composio,
  `connections.py:22-33`) or prompted URL/stdio-command; for http(s) tries
  `connect_oauth` FIRST; on failure falls back to API-key header
  (`x-consumer-api-key` for *.composio.dev, :36-46) or Bearer token.
- `oauth.py` — full MCP OAuth 2.1 in stdlib: RFC 9728 protected-resource
  discovery (2 probe paths, :86-96) -> RFC 8414/oidc AS metadata (3 probe
  paths, :98-110) -> RFC 7591 dynamic client registration ("Clacky",
  `token_endpoint_auth_method:"none"`, :141-153) -> auth-code + PKCE S256 +
  `resource` binding (RFC 8707) in the browser, one-shot 127.0.0.1:0 callback
  server, state check, token exchange (:128-205). Bundle {access, refresh,
  expires_at, token_endpoint, client_id, resource}: access -> hermes config
  `headers.Authorization: Bearer`; bundle -> `~/.clacky/connections.json`;
  `refresh_stale()` re-mints + rewrites config before bg tasks
  (`connections.py:163-185`).
- `add_server` merges `mcp_servers` into hermes' own config path — resolved
  via `hermes_constants.get_hermes_home()` (`%LOCALAPPDATA%\hermes` on
  Windows, not `~/.hermes`, :49-59).
- Exposure model: MCP tools exist ONLY in the bg lane (ACP mounts them); the
  foreground act loop has no MCP — deliberate local-first split.
- JIT connect: `ui/connect_dialog.py` — offer when a task names a missing
  app; known OAuth apps = one Connect button; skip => files fallback;
  on_done(bool) exactly once.
- `COMPOSIO_API_KEY` env auto-connects at manager init
  (`companion_manager.py:315-324`).

## 8. `clacky organize` — HIGH confidence

- Flow (`cli.py:31-76` -> `agent/runtime.py:21-54`): check_root ->
  `planner.build_plan` -> execute via fileops -> `journal.save`.
- LLM call (`agent/planner.py:85-124`): one `provider.complete(SYSTEM_PROMPT,
  json)`; context = {name, ext, size, peek<=600B for .txt/.md/.csv/...}
  (:75-82). Reply = `{"moves":[{"name","folder","reason"}]}`; `_extract_json`
  tolerates fences/preamble, falls back to outermost `{}` (:34-50). Any
  provider incl. `heuristic` (extension map, `providers/heuristic.py`).
- Validation: hallucinated names dropped; every move re-checked by
  `fileops.check_move` — home-only root, protected dirs, protected suffixes
  (.sys/.dll/.exe/.lnk), sensitive name hints, dst must stay under root,
  MAX_BATCH=200 (`agent/fileops.py:15-62`). Move-only; collision -> ` (n)`.
- Undo log: `agent/journal.py` — `~/.clacky/history/batch_<ts>.json`
  `{when, records:[{src,dst}]}`; `undo_last` replays in reverse order,
  consumes file. Survives restarts.
- Voice wiring (`actions.py:88-160`): folder picked by keyword
  (Desktop/Downloads/Documents); provider = configured (claude->Haiku via
  `CLACKY_ORGANIZE_MODEL`) with heuristic fallback on ANY failure (double
  retry, :119-129); `CLACKY_MOVE_STAGGER=0.12`s between moves so icons
  visibly vanish one-by-one; `_tidy_desktop_icons` sorts remaining desktop
  icons via `Shell.Application` COM `SortColumns="prop:System.
  ItemNameDisplay;"`, fallback WM_COMMAND 0x7021 posted to ALL
  SHELLDLL_DefView under Progman AND WorkerW (:36-86).
- Voice undo: route `undo` + permissive local regex incl. STT misspellings
  ("undue/on-do/and do", `companion_manager.py:774-788`).

## 9. Screen / overlay — HIGH confidence

- `ui/overlay.py`: PyQt6 frameless always-on-top `Tool` window,
  `WA_TranslucentBackground` + `WA_TransparentForMouseEvents` (click-through)
  + `WA_ShowWithoutActivating` (:112-121); geometry = union of all screens
  (:250-254); 60fps QTimer.
- Buddy: blue triangle (+35,+25 from cursor) with spring-follow
  (stiffness .28/damping .62); modes idle/listening=5-bar waveform/
  thinking=spinner/speaking.
- Pointing: `point_at(x,y,label)` -> quadratic bezier flight, arc apex above
  midpoint (<=90px), duration 0.35-0.7s scaled by distance, rotation to
  tangent, scale pulse (:224-242, 267-311); dwell 4s or infinite when
  `set_point_hold(True)` while TTS runs; `release_point` -> 1.4s return
  flight; optional speech-bubble (eased alpha/scale, real labels only — empty
  label => no bubble).
- Whiteboard: `add_arrow/circle/underline/text` with TTL 8s, fade in last
  25% (:194-222, 382-443). `set_slow_mode` x1.7 all timings.
- **Tour mode** (`tour.py::_run_narration`, 189-397): ONE streaming model
  call; system prompt demands `[POINT:x,y] <one sentence>` lines for 3-4
  elements, tag BEFORE its sentence (:232-247). SSE `text_delta` stream —
  a segment completes when the NEXT tag appears; producer starts `synth`
  per segment immediately; consumer plays in order (gapless), firing the
  point exactly as that sentence's audio starts. Design note worth copying
  (:4-9): pointer timing derived from tag position in the SAME text channel —
  a multi-turn tool loop is structurally one step late (each turn's text
  describes the previous move). Batch fallback only if the stream yielded
  nothing; mid-stream death ends early, never replays (:273-346). Model
  coords get `_snap_to_uia` nudge (:223-230).

## 10. Permissions / safety — HIGH confidence (with an honest gap)

- Live act-loop safety = prompt restraint + MAX_STEPS=12 + Esc/barge-in +
  "stop before irreversible" system prompt. **The 4-tier classifier is NOT
  wired into the live loop** — `classify_action`/`needs_confirm`
  (`agent/permission.py:111-140`) only gate the scaffold `ComputerAgent` and
  `narrator.py` (which IS exercised via `_blocked`, :154-157, but that loop
  isn't called by the shell either — no callers). Tests cover only
  `classify_move` (`tests/test_clacky_core.py:69-73`). docs/AGENT_PLAN.md
  markets the gate; reality is prompt-only.
- The classifier itself is well-designed: SAFE (read-only incl. point/say
  narration tools) / REVERSIBLE (journaled file moves) / CAUTION (routine GUI
  mutation -> narrate) / DANGEROUS (danger-substring on UIA label/role — send/
  delete/buy/submit/confirm/share... — **or any click whose target UIA couldn't
  resolve**: default-deny). Typed text deliberately NOT scanned — danger is a
  property of the target control (:115-119).
- Privacy guard: `is_sensitive_window` regex on window title (password/
  banking/login/.env...) -> NO screenshot + prompt note telling the model why
  (`companion_manager.py:911-913, 1068-1074`; `tutor.py:160-168`).
- Identity-question screenshot strip: "who is X" queries drop screenshots so
  vision-safety refusals can't fire; answer via training + web search
  (`tutor.py:120-139`, `companion_manager.py:903-915`).
- Audit: `session_log.slog` — timestamped flight recorder
  (~/.clacky/logs/session.log) with per-turn elapsed clock (`turn()` resets
  t0); categories HEAR/ROUTE/THINK/SAY/POINT/SNAP/ACT/TTS/BG/SKILL.
- Kill paths: Esc (`StopHotkey`) -> `_cancel_flag` + global `stop_audio()`
  (~50ms); hotkey re-press = barge-in; bg timeout + file salvage; mic/loop
  restart after sleep.
- Bg-lane hardening (see section 6): env secret scrub, evidence-checked LINKs,
  composio.dev host allowlist for auto-opening auth URLs, ACP fs
  capabilities declared false, per-task workspace cwd.

## 11. Other things worth stealing

- Warm shared httpx/Anthropic clients per manager; reset on error (stale
  pool after sleep) — `routing.py:28-49`, `element_locator.py:34-42`.
- `_action_label` cursor pill: model emits a 2-4-word note per action —
  makes an agent's work legible without TTS noise (`actions.py:530-550`).
- `_guess_label` (219-231): noun-phrase extraction for the point bubble.
- `_split_complete_sentences`: whitespace-required boundary — never chops
  mid-token on stream boundaries (:1311-1324).
- Tag hygiene on streamed text: `ANY_PARTIAL_RE` holds back unclosed
  `[POINT...` tags so they never flash into UI (:245-252, :1158-1166).
- Dedup points per label; suppress LLM-point when detector already pinned
  (:1020-1031).
- Web search sidecar (`ai/web_search.py`): free path = ddgs lib (fallback DDG
  HTML scrape) -> fetch top-3 pages -> strip to text, 1400-char/page,
  5500-char total, cite [1][2]; recency year-appended query expansion;
  Tavily premium path.
- Model registry (`ai/model_registry.py`): live /v1/models fetch per
  provider, 30-day TTL cache + curated fallbacks; Copilot device-flow gives a
  free LLM seat (`github_copilot_provider.py` — VS Code public client_id,
  /models with billing multiplier, 6h cache).
- Ollama bootstrap: `_ensure_ollama_running` launches `ollama serve`
  detached, 8s ready poll; `ollama_bootstrap.py` lists/pulls with progress.
- Apps launcher pattern: built-in map + user `~/.clacky/apps.json` overrides
  (exe candidates then URL protocols), web-app fallback for "check my email"
  -> logged-in browser (`actions.py:574-681`).
- Sleep/wake watchdog via heartbeat drift (`companion_manager.py:456-495`).
- Diagnostics dump (`main.py:283-327`); PyInstaller spec excludes list saved
  ~1.8GB (tensorflow/torch/etc.) to fit GitHub's 2GiB release cap
  (`clacky.spec:64-74`).
- Prompt craft worth copying: "for the ear" constraints everywhere; tour
  format contract; bg-worker past-tense + LINK: protocol; workspace "name
  the recipient aloud"; act-loop "STOP the moment the goal is visibly
  achieved"; DETECTED ELEMENT ctx line telling the model the cursor is
  already on it so it names it instead of emitting coordinates.
- `docs/AGENT_PLAN.md` + `SCOPE.md` — candid design-history docs (v3 "one
  structured call, model never touches disk" -> v4 "the loop comes back for
  GUI actions"); the seam-analysis table (:26-37) is a good pattern for
  vendoring.

## Wisp adoption notes

- **Steal wholesale**: LINK-evidence verification (s6), CONNECT-<app>.txt
  handshake + bounded retry (s6), Haiku-forced-tool router w/ local fast-path
  (s2C), single-stream tour with sentence-synced points (s9), streaming-STT
  during push-to-talk + prewarmed screenshot + pre-baked acks (s3),
  journaled move-only organize + voice undo incl. STT-misspelling regex (s8),
  env secret-scrub for delegated agents (s6/s10), per-app history keyed by
  focused window (s2), nudge-snap with container guard (s1), whitespace-
  required sentence splitting for streaming TTS (s3).
- **Adapt**: UIA->AT-SPI for tier-1 pointing (same _score_match logic applies);
  WindowsActuator->wisp's cua-driver; overlay beacons can reuse the flight/
  dwell/release state machine and TTL annotation fade.
- **Skip**: Windows-only machinery (COM icon sort, mss, App Paths), the
  regex->handler python skills (wisp's skills module supersedes), tutor/
  quiz/lesson/collab features, Copilot provider (billing-gray), the unwired
  permission scaffold — but DO steal its 4-tier design + default-deny, since
  wisp's verification ladder is where the gate should plug in.
- **Caution**: live act loop has prompt-only safety (s10) — treat the
  "pauses before irreversible" claim as aspiration, not mechanism.
