# Wisp Roadmap

State: **Phases 1–9 are on `master` / `feat/wisp-unified-alignment-and-polish`, plus units B1–B34 of the beat-competitors plan (except B3/B31), Phases A–D (bar, rating, Dev tab, voice), and Unification Waves U1–U10 (single-shot VLM grounding, pointer `auto` driving, deictic routing + OpenCode CWD inference, web service aliases + tab-first launch, sensitive T2 surface gating, QML pill continuity, Particle AI `particle-ai/particle-1` OpenCode default + OpenRouter provider routing, multi-browser profile Personal/Work & tab intelligence, talkback confirmation + Settings voice controls, and Omarchy Quickshell Settings card UX).**
Last updated: 2026-10-30. Plan of record: `docs/plans/2026-10-30-001-feat-wisp-unified-alignment-and-polish-plan.md` (building on `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md`). This is the only roadmap; `docs/ROADMAP.md` points here.

## Product target

A push-to-talk voice companion for Hyprland/Omarchy. You hold the hotkey and speak. Wisp answers by voice while pointing and drawing on the screen, walks you through multi-step tasks, and runs background agents and routines. Autonomous clicking (act/cua) stays, but it is secondary.

Fixed decisions:

- Hosted models only. Local model servers are opt-in and off (`[local] enabled`).
- Linux only.
- One end-to-end eval (`wispd eval`) is the v1 gate.
- The Rust core in `rs/` is frozen.
- No decision model on the routing path: turns go to the act loop, and the regex heuristic becomes a fast path in Phase 5.

## Shipped

1. OpenRouter-only defaults and the act router (#139).
2. Agent safety and routines: IPC read/mutate split, truthful task outcomes, CLI and voice-taught routines (#141).
3. Linux-only code, CI and releases (#143).
4. Training stack removed; `wispd eval` added (#144).
5. Phase 6 · Hosted install: Groq speech-to-text default, onboarding asks for keys, `wispd install --ref` (#146).
6. Phase 7, first surfaces: Clacky-style cursor buddy (#148, #149), points fire as their sentence starts playing (#150), rings, arrows and highlights drawn on screen (#152, R5 and R6).

7. Phase 7, the rest: sensitive-window skip (#158), per-app chat history, barge-in and streaming speech-to-text (#160–#162, R8), spoken walkthroughs with label-first snapping (#163, R7).
8. Phase 8 · Agent hardening: Wisp-held credentials scrubbed from spawned agents (#155, R11).
9. Beat-competitors plan (`docs/plans/2026-10-27-feat-wisp-beat-competitors-plan.md`), B1–B34 except B3 and B31 (#164–#204): latency gate, earlier first sentence, hand-drawn ink, image cards, walkthrough lessons, scribble to ask, voice speed, document context, named helpers, plan preview, install and trust pages, multilingual turns, dictation safety net, sharing, capture checks, one-instance daemon, self-answers, starter pack, hands-free mode, and a capped trial brain (off).

9. Bar, ratings, Dev tab and voice (phases A to D, `docs/plans/2026-10-28-2233-feat-bar-feedback-devtab-voice-plan.md`):
   - **A, one-tap ratings (#238):** every turn's decision line carries its turn id, so a rating lands on the turn it was given for. The answer card has thumb buttons, and **Super+Alt+D** rates the last finished turn wrong and opens a one-line note.
   - **B, bar status pill (#246):** the bar pill names the state in a word with its own glyph, and a finished turn shows an 8 second rating window.
   - **C, Dev tab (#247):** `wispd dev turns` and a local-only fifth Panel tab (`[dev] panel = true`, off by default) show the v1 gate tally, recent turns with per-stage time and the top misses.
   - **D, talk-back (#244):** answers are spoken through Groq Orpheus when a Groq key resolves, with espeak as the fallback, and `wispd doctor` gains a voice section.
   - **Also:** the test suite no longer reads the live desktop (#245), dead helpers and imports are gone (#248), and the no-daemon trigger fallback now records privately like the daemon: umask 077, private folders, one shared setup (#250).

10. Unified Alignment & Polish (`docs/plans/2026-10-30-001-feat-wisp-unified-alignment-and-polish-plan.md`, #259):
    - **U1, single-shot VLM grounding (`wisp/grounding.py`, `wisp/config.py`):** added `"vlm"` to `[ground] providers = "control,a11y,vlm,jev"` using HeyClicky's aspect-ratio bucket table (`1024x768`, `1280x800`, `1366x768`) before the 9-call Jev grid bisection fallback.
    - **U2, pointer `auto` driving (`wisp/config.py`, `wisp/tools/pointer.py`):** changed `[pointer] mode` default to `"auto"` and wired `auto` into `click`/`move`/`scroll` so the act loop drives real clicks while keeping guide mode available.
    - **U3, deictic routing & OpenCode CWD inference (`wisp/route.py`, `wisp/agents.py`, `wisp/stage_route.py`):** screen/error/debug questions (`"tell me what this does"`, `"what's wrong here"`, `"debug this"`) bypass blind fast-path text answers and attach live screen context; background OpenCode tasks infer the active git repo from the focused window title or prompt.
    - **U4, web service aliases & tab-first launch (`wisp/tools/desktop.py`, `wisp/config.py`):** natural spoken targets (`"check my email"`, `"go to my Stripe"`, `"go to my Linear"`, `"GitHub"`, `"Notion"`, `"Slack"`) switch to an already-open browser tab first or open the configured service URL.
    - **U5, sensitive web surface T2 gating (`wisp/policy.py`):** mutating actions (`click`, `type_text`, `fill`, `key`, `post_send`) on financial/admin surfaces (`stripe`, `robinhood`, `plaid`, `mercury`, `brex`, `wise`, `paypal`, `coinbase`, `ibkr`) promote to T2 confirmation even when `autonomy = "autonomous"`.
    - **U6, QML pill & notch HUD continuity (`shell-plugin/lib/companion.js`):** listening pill stays visible across `listening`, `transcribing`, `deciding`, `acting`, `speaking`, and `awaiting_choice`, handing off cleanly to `Bubble.qml` (parked top-center under the Omarchy bar) when a confirmation card or spoken answer arrives.
    - **U7, Particle AI (`particle-ai/particle-1`) & OpenRouter provider routing (`wisp/acp_runtime.py`, `wisp/config.py`, `wisp/brain.py`):** promoted `openrouter/particle-ai/particle-1` (Particle AI's post-trained DeepSeek V4.1 Flash agentic model) to the primary OpenCode ACP model ahead of `deepseek-v4-flash`, and added optional `provider_order` / `provider_sort` routing to `brain.py`.
    - **U8, multi-browser profile (`Personal` vs `Work`) & tab intelligence (`wisp/tools/desktop.py`, `wisp/context.py`, `wisp/act.py`):** `tab()` and `launch()` detect `Personal` vs `Work` from the utterance (`"for work"`, `"on personal"`) or fall back to the currently focused browser window's profile, scan all active CDP ports, and inject `profile=personal|work` into `[focus]`.
    - **U9, talkback confirmation & Settings voice controls (`wisp/stage_speak.py`, `wisp/settings_schema.py`, `wisp/copy.py`):** direct tool actions (`SWITCHED tab`, `OPENED`, `LAUNCHED`, `FOCUSED`, `WORKSPACE`) now speak concise confirmations aloud and render clean human copy in the bubble; `voice.enabled`, `voice.tts_voice`, and `voice.captions` are editable directly in the Panel Settings tab.
    - **U10, Omarchy Quickshell Settings & StatusLine UX (`shell-plugin/components/SettingsTab.qml`, `shell-plugin/components/StatusLine.qml`):** grouped Panel Settings into clean surface cards (`voice and talkback`, `dictation`, `pointer` + `agent`, `cua safety`, `budget`, `connectors`) with `on`/`off` toggle labels, and added a quick `talk`/`stop` chip to `StatusLine`.

Also: CI flake root causes (#142), "open my email" opens Gmail when the mail handler is a browser (#147), Argus pinned at c701b2a (#151), act no longer ends a run on a narrated next step without a tool call (#153). Voice polish leftovers (B8b): captions toggle, mic failover, muted speaker keeps the answer on the clipboard, and no announcements on calls. Watchable browser lane (B14): an extension pairs with a code and works in a tab group in your own browser, off by default.  3D parts (B13): an answer can carry one small allow-listed glTF model whose parts you click to ask about.

- **Dev tuning mode & per-model TTFT/latency benchmarking** — `wispd dev on|off|run|runs|review` (`wisp/devsession.py`, `wisp/devrun.py`, `wisp/devjudge.py`, `wisp/devreport.py`) runs deterministic task lists (`docs/dev-tasks/starter.txt`) with an LLM judge, A/B arms, and drift flags; `wisp/brain.py`, `wisp/telemetry.py`, `wisp/devlog.py`, and `wispd latency` report per-call `ttft_ms`, `latency_ms`, and per-model p50/p90 tables.
- **App skill ingestion, provenance & live `[app_skill]` injection** — `scripts/skill_distill.py` (`--ingest`, `--from-routines`, `--backfill-routing`, `--validate`), provenance-checked frontmatter (`source`, `app_classes`, `url_hosts`, `asks`), `codebase-graph` + `graphify` seed skills, and automatic `[app_skill]` prompt injection in `context.snapshot("full")` and `memory.context_block()`.
- **Cross-platform macOS & Windows telemetry/action probe seams** — Linux (Omarchy/Hyprland) remains the primary full desktop experience, while `wisp/platform.py` and `wisp/ipc.py` mirror `rs/wispd/src/platform.rs` with macOS (`screencapture`, `osascript`, `sox`/`ffmpeg`, `say`) and Windows (`CopyFromScreen`, `user32.dll`, TCP loopback IPC) adapters so cross-OS telemetry and task runs work out of the box.

## Next, in order

Each is one PR, planned when it starts.

1. **Phase 9 · Act quality** — shipped so far: default-app resolution (#147), open-tab switching and no unconfirmed success claims (#212), "go to a site" opens in the user's browser instead of `xdg-open` (#231), clicks that land off every monitor are refused so the loop re-aims (#232), and multi-profile browser tab switching + active `[app_skill]` injection (#259). Left: run `wispd dev run` on the starter task list and re-rank from `wispd eval --misses` / `wispd dev review` over 50+ turns. Unblocks B3.
2. **Phase 5 · Router fast path** — shipped so far: the regex fast path in front of act (#233; bare launches of catalogued apps and plain questions skip the act loop, `[brain] fast_path`), removal of the shadow decider (#234), the flash lane and the route A/B log (#235), and removing dead `jev-1.13` HTTP calls from `grounding.py` and `suggest.py` (#259). Left: remove the legacy `router = jev` branch (`route.decide`, `ask_jev`, `JEV_QUESTIONS`, the clarify prompt) after migrating the 45 replay fixtures that still script `router = jev`.
3. **Verified install, `wisp.casa` bootstrap & update** (`docs/plans/2026-10-29-2302-feat-verified-install-update-plan.md`) — shipped so far: a shared preflight, a backed-up and verified `wispd update` with `--rollback`, `wispd config preset {cloud,local,safe}`, and the stage and recovery docs. Left: wire the signed one-line bootstrap on `wisp.casa` (`https://wisp.casa/install.sh` + `https://trial.wisp.casa/v1` proxy DNS), plugin/unit recovery, and the local-model promotion gate.
4. **Remaining plan units** — B3 (accuracy loop, after Phase 9), B31 (growth scoreboard).
5. **Clean-box check** — `wispd onboard` and `wispd doctor` on a clean Omarchy box with hosted keys only.
6. **Next-horizon desktop overlays & cross-OS companions (post-v1)** — interactive scratchpad mini-explainer card (building on `note.py` paper strip and `Bubble.qml`), richer on-screen 3D model generation/inspection overlays (building on `ModelCard.qml` and `lib/model3d.js`), and lightweight macOS/Windows menu-bar/tray companions powered by `rs/wispd` and the cross-OS platform seams.

## v1.0 gate

- [ ] `wispd eval` passes `[eval] gate_rate` (`60%`, decided by the owner 2026-10-27) over at least 50 labelled turns.
- [ ] `wispd onboard` and `wispd doctor` pass on a clean Omarchy box with hosted keys only.
- [ ] Tag `v1.0.0`.

Tally (`wispd eval`, 2026-10-28): 23 labelled turns, 7 right first time (30%) — act 4/15 (9 retried), answer 0/2, launch 1/2, other 2/4. Gate set to 60% (needs 27 more labelled turns and a higher rate).

## Open decisions

- **Clacky extras.** Streaming speech-to-text and barge-in shipped (#161, #162). Recommended: drop journaled organize and deferred auth for v1.

## Not doing

- Local-first operation, local model ladders or backend toggles.
- Model training, distillation or per-route soak tooling.
- Cross-platform ports.
- A decision model (Jev or pplx) in front of routing.
