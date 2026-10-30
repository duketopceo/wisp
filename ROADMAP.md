# Wisp Roadmap

State: **v0.9 shipped; v1.0 remains a verification milestone.** Earlier merged work is listed under Shipped. Unified alignment, release completion, dev tuning, app skills and platform probe seams are on `feat/wisp-unified-alignment-and-polish` in **open PR #259**, not yet shipped.
Last updated: 2026-10-30. Plan of record: `docs/plans/2026-10-30-001-feat-wisp-unified-alignment-and-polish-plan.md` (building on `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md`). This is the only roadmap; `docs/ROADMAP.md` points here.

## Product target

A push-to-talk voice companion for Hyprland/Omarchy. You hold the hotkey and speak. Wisp answers by voice while pointing and drawing on the screen, walks you through multi-step tasks, and runs background agents and routines. Autonomous clicking (act/cua) stays, but it is secondary.

Fixed decisions:

- Hosted models by default. Local model servers are opt-in and off (`[local] enabled`).
- Linux (Omarchy/Hyprland) is the primary supported desktop. macOS/Windows probe seams in PR #259 are experimental, not supported desktop releases.
- One end-to-end eval (`wispd eval`) is the v1 gate.
- The Rust core in `rs/` is frozen.
- No decision model on the routing path: turns go to the act loop, and the regex heuristic becomes a fast path in Phase 5.

## Shipped

1. OpenRouter-only defaults and the act router (#139).
2. Agent safety and routines: IPC read/mutate split, truthful task outcomes, CLI and voice-taught routines (#141).
3. Linux-only code, CI and releases at that milestone (#143); experimental probe seams in PR #259 do not change the supported release target.
4. Training stack removed; `wispd eval` added (#144).
5. Phase 6 · Hosted install: Groq speech-to-text default, onboarding asks for keys, `wispd install --ref` (#146).
6. Phase 7, first surfaces: Clacky-style cursor buddy (#148, #149), points fire as their sentence starts playing (#150), rings, arrows and highlights drawn on screen (#152, R5 and R6).

7. Phase 7, the rest: sensitive-window skip (#158), per-app chat history, barge-in and streaming speech-to-text (#160–#162, R8), spoken walkthroughs with label-first snapping (#163, R7).
8. Phase 8 · Agent hardening: Wisp-held credentials scrubbed from spawned agents (#155, R11).
9. Beat-competitors plan (`docs/plans/2026-10-27-feat-wisp-beat-competitors-plan.md`), B1–B34 except B3 and B31 (#164–#204): latency gate, earlier first sentence, hand-drawn ink, image cards, walkthrough lessons, scribble to ask, voice speed, document context, named helpers, plan preview, install and trust pages, multilingual turns, dictation safety net, sharing, capture checks, one-instance daemon, self-answers, starter pack, hands-free mode, and a capped trial brain (off).

10. Bar, ratings, Dev tab and voice (phases A to D, `docs/plans/2026-10-28-2233-feat-bar-feedback-devtab-voice-plan.md`):
   - **A, one-tap ratings (#238):** every turn's decision line carries its turn id, so a rating lands on the turn it was given for. The answer card has thumb buttons, and **Super+Alt+D** rates the last finished turn wrong and opens a one-line note.
   - **B, bar status pill (#246):** the bar pill names the state in a word with its own glyph, and a finished turn shows an 8 second rating window.
   - **C, Dev tab (#247):** `wispd dev turns` and a local-only fifth Panel tab (`[dev] panel = true`, off by default) show the v1 gate tally, recent turns with per-stage time and the top misses.
   - **D, talk-back (#244):** answers are spoken through Groq Orpheus when a Groq key resolves, with espeak as the fallback, and `wispd doctor` gains a voice section.
   - **Also:** the test suite no longer reads the live desktop (#245), dead helpers and imports are gone (#248), and the no-daemon trigger fallback now records privately like the daemon: umask 077, private folders, one shared setup (#250).

Also: CI flake root causes (#142), "open my email" opens Gmail when the mail handler is a browser (#147), Argus pinned at c701b2a (#151), act no longer ends a run on a narrated next step without a tool call (#153). Voice polish leftovers (B8b): captions toggle, mic failover, muted speaker keeps the answer on the clipboard, and no announcements on calls. Watchable browser lane (B14): an extension pairs with a code and works in a tab group in your own browser, off by default.  3D parts (B13): an answer can carry one small allow-listed glTF model whose parts you click to ask about.

## In PR #259 — not yet shipped

1. Unified Alignment & Polish (`docs/plans/2026-10-30-001-feat-wisp-unified-alignment-and-polish-plan.md`, #259):
    - **U1, single-shot VLM grounding (`wisp/grounding.py`):** added a `"vlm"` provider and an aspect-matched VLM attempt inside the existing `"jev"` candidate before legacy pointing fallback. The configured provider chain remains `"control,a11y,uitars,jev"`; actual pointing quality and latency still need live evaluation.
    - **U2, pointer `auto` driving (`wisp/stage_execute.py`, `wisp/tools/system.py`, `wisp/realinput.py`):** `auto` can use a live injection backend. Unconfigured act turns use a temporary `auto` overlay only when a backend exists; explicit modes, including persisted `guide`, are preserved. This is not a permanent default/config rewrite or proof of live cursor behavior.
    - **U3, deictic routing & OpenCode CWD inference (`wisp/route.py`, `wisp/agents.py`, `wisp/stage_route.py`):** screen/error/debug questions (`"tell me what this does"`, `"what's wrong here"`, `"debug this"`) bypass blind fast-path text answers and attach live screen context; background OpenCode tasks infer the active git repo from the focused window title or prompt.
    - **U4, web service aliases & tab-first launch (`wisp/tools/desktop.py`, `wisp/config.py`):** natural spoken targets (`"check my email"`, `"go to my Stripe"`, `"go to my Linear"`, `"GitHub"`, `"Notion"`, `"Slack"`) switch to an already-open browser tab first or open the configured service URL.
    - **U5, sensitive web surface T2 gating (`wisp/policy.py`):** mutating actions (`click`, `type_text`, `fill`, `key`, `post_send`) on financial/admin surfaces (`stripe`, `robinhood`, `plaid`, `mercury`, `brex`, `wise`, `paypal`, `coinbase`, `ibkr`) promote to T2 confirmation even when `autonomy = "autonomous"`.
    - **U6, QML pill & notch HUD continuity (`shell-plugin/lib/companion.js`):** listening pill stays visible across `listening`, `transcribing`, `deciding`, `acting`, `speaking`, and `awaiting_choice`, handing off cleanly to `Bubble.qml` (parked top-center under the Omarchy bar) when a confirmation card or spoken answer arrives.
    - **U7, configured model order & provider routing (`wisp/acp_runtime.py`, `wisp/config.py`, `wisp/brain.py`):** the OpenCode ACP candidate list starts with `openrouter/particle-ai/particle-1`, ahead of `deepseek-v4-flash`; `brain.py` accepts optional `provider_order` / `provider_sort`. Alias availability, billing and live provider quality are not verified by configuration or unit tests.
    - **U8, multi-browser profile (`Personal` vs `Work`) & tab intelligence (`wisp/tools/desktop.py`, `wisp/context.py`, `wisp/act.py`):** `tab()` and `launch()` detect `Personal` vs `Work` from the utterance (`"for work"`, `"on personal"`) or fall back to the currently focused browser window's profile, scan all active CDP ports, and inject `profile=personal|work` into `[focus]`.
    - **U9, talkback confirmation & Settings voice controls (`wisp/stage_speak.py`, `wisp/settings_schema.py`, `wisp/copy.py`):** direct tool actions (`SWITCHED tab`, `OPENED`, `LAUNCHED`, `FOCUSED`, `WORKSPACE`) now speak concise confirmations aloud and render clean human copy in the bubble; `voice.enabled`, `voice.tts_voice`, and `voice.captions` are editable directly in the Panel Settings tab.
    - **U10, Omarchy Quickshell Settings & StatusLine UX (`shell-plugin/components/SettingsTab.qml`, `shell-plugin/components/StatusLine.qml`):** grouped Panel Settings into clean surface cards (`voice and talkback`, `dictation`, `pointer` + `agent`, `cua safety`, `budget`, `connectors`) with `on`/`off` toggle labels, and added a quick `talk`/`stop` chip to `StatusLine`.

- **Dev tuning mode & per-model timing (PR #259):** `wispd dev on`, `wispd dev off`, `wispd dev run`, `wispd dev runs`, and `wispd dev review` use task lists (`docs/dev-tasks/starter.txt`), a judge, A/B arms, and drift flags. The upstream #260 safety follow-up is included on this branch. Streaming content can measure first-token time; complete-response calls report TTFT unavailable and total latency separately. These are instruments for future runs, not new live benchmark results.
- **App skill ingestion, provenance & live `[app_skill]` injection** — `scripts/skill_distill.py` (`--ingest`, `--from-routines`, `--backfill-routing`, `--validate`), provenance-checked frontmatter (`source`, `app_classes`, `url_hosts`, `asks`), `codebase-graph` + `graphify` seed skills, and automatic `[app_skill]` prompt injection in `context.snapshot("full")` and `memory.context_block()`.
- **Experimental macOS & Windows telemetry/action probe seams (PR #259)** — Linux (Omarchy/Hyprland) remains the primary supported desktop. `wisp/platform.py` and `wisp/ipc.py` add macOS (`screencapture`, `osascript`, `sox`/`ffmpeg`, `say`) and Windows (`CopyFromScreen`, `user32.dll`, TCP loopback IPC) probe adapters, mirroring `rs/wispd/src/platform.rs`. These seams are not proof of a verified full pipeline, packaged companion, or supported cross-OS release.
- **U14–U18 delivery completion (PR #259):** media/capture cleanup regressions, an optional self-hosted Three.js illustration in `site-3d/`, explicit confirmation/reset/motion controls, deterministic builds, browser fixtures, and documentation checks. The no-script `site/` build remains independent. A private preview is not activation of `wisp.observer`; Linux media, QML, model-backed tasks and fresh-box checks still require real-device receipts.
- **Release-completion work in progress:** complete extracted-archive installs, versioned one-line bootstrap, onboarding and attributable plugin/unit recovery; element-backed click provenance and an honest accuracy-data importer; replay migration before legacy router removal; a public growth snapshot and an opt-in local weekly recap. Completion requires integrated tests and independent source review, not only implementation reports.

## Next, in order

Owner's delivery order: installable app first, owner-labelled runs second, measured tuning third. An installable release candidate is not a waiver or a pass of the stable-v1 gate.

1. **Installable candidate:** finish the current release-completion work, verify actual extracted archives and recovery, pass review and CI, then publish a versioned Linux release. Provide one install line and an onboarding path. Validate drawing, pointing, rings, arrows, highlights and guided steps in the available harness; keep real compositor and microphone checks explicitly pending for the owner's reinstall.
2. **Owner onboarding and real runs:** reinstall on Omarchy, complete `wispd onboard` and `wispd doctor` with hosted keys, then run a varied set of real tasks across apps. Collect labels with the existing feedback controls, `wispd eval`, and `wispd dev review`. Run `wispd dev run` only in an explicitly approved session. Judge output is not an owner label.
3. **Accuracy and app-skill loop:** rank actual misses, preserve reproducible failing tasks, improve grounding/routing and provenance-checked app skills, then retest on held-out tasks. B3's historical baseline cannot be reconstructed without the original data; importing synthetic fixtures is not evidence of live improvement.
4. **Stable v1:** pass the owner-labelled accuracy and clean-box gates below before tagging `v1.0.0`. Public snapshots and an optional private weekly recap are diagnostic surfaces, not proof of product success.
5. **Model learning later:** consider actual fine-tuning or reinforcement learning only after clean outcome labels, safety review and a held-out evaluation exist. Do not rebuild the removed training stack merely to ship this candidate.
6. **Post-v1 companions:** interactive scratchpad mini-explainers, richer on-screen 3D generation/inspection, and lightweight macOS/Windows menu-bar or tray companions. Experimental adapters do not constitute supported full desktop ports.

`wisp.observer` remains the intended primary domain, not a verified deployment.
Publish the homepage and bootstrap only after authenticated DNS access, HTTPS,
artifact checks and an actual install-command receipt. Release checksums are
not a signature or an independent signing trust root; no signed-bootstrap
claim is made without one. The trial proxy remains off.

Companion follow-up: the pill continuity change is implemented, but
`buddy.js` still uses its 0.30-second entry delay. R6's proposed reduction
needs a real capture/overlay check before changing screenshot-clearance
timing. No native GUI smoothness or latency improvement is inferred from
the browser illustration.

## v1.0 gate

- [ ] `wispd eval` passes `[eval] gate_rate` (`60%`, decided by the owner 2026-10-27) over at least 50 labelled turns.
- [ ] `wispd onboard` and `wispd doctor` pass on a clean Omarchy box with hosted keys only.
- [ ] Tag `v1.0.0`.

Historical tally (`wispd eval`, 2026-10-28; not a current gate result): 23 labelled turns, 7 right first time (30%) — act 4/15 (9 retried), answer 0/2, launch 1/2, other 2/4. Gate set to 60% (at that snapshot, needed 27 more labelled turns and a higher rate).

## Open decisions

- **Clacky extras.** Streaming speech-to-text and barge-in shipped (#161, #162). Recommended: drop journaled organize and deferred auth for v1.

## Not doing

- Local-first defaults or automatic local model promotion; explicit opt-in local model servers remain available.
- Model training or distillation in the installable candidate; future learning requires real data and an explicit separate decision.
- Supported full macOS/Windows desktop ports for v1; experimental probe seams are not such ports.
- A decision model (Jev or pplx) in front of routing.
