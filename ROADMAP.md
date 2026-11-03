# Wisp Roadmap

State: **v1.0.0-rc.2 is published as a Linux prerelease (6 assets, 2026-10-30); stable v1.0 remains a verification milestone.** GitHub's "Latest" release is still v0.9.0 because rc.2 is a prerelease. `pyproject.toml` and `wisp/__init__.py` say 1.0.0. Unified alignment, release completion, dev tuning, app skills and platform probe seams merged in #259 (tagged `v1.0.0-rc.1`); release and install fixes followed in #262 (tagged `v1.0.0-rc.2`), #263 and #264. The gauntlet, the isolated session and the default-brain change landed after rc.2 (#273-#305).
Last updated: 2026-11-03 (read from `master` at `898258e`). Plan of record: `docs/plans/2026-10-30-001-feat-wisp-unified-alignment-and-polish-plan.md` (building on `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md`); the gauntlet work follows `docs/plans/2026-11-01-0008-feat-wisp-gauntlet-v1-plan.md`. This is the only roadmap; `docs/ROADMAP.md` points here.

## Product target

A push-to-talk voice companion for Hyprland/Omarchy. You hold the hotkey and speak. Wisp answers by voice while pointing and drawing on the screen, walks you through multi-step tasks, and runs background agents and routines. Autonomous clicking (act/cua) stays, but it is secondary.

Fixed decisions:

- Hosted models by default: the brain is `openrouter:google/gemini-2.5-flash` (#299), and the shipped `[brain] fallback` is empty. Local model servers are opt-in and off (`[local] enabled`).
- Linux (Omarchy/Hyprland) is the primary supported desktop. macOS/Windows probe seams in PR #259 are experimental, not supported desktop releases.
- One end-to-end eval (`wispd eval`) is the v1 gate.
- The Rust core in `rs/` is frozen.
- No decision model on the routing path: turns go to the act loop, with the regex fast path (`[brain] fast_path`) in front. Phase 5 is done in `wisp/`: the Jev router, `route.decide`, the clarify prompt and `JEV_QUESTIONS` are gone (#259), the replay harness no longer pins `router = jev` (#261), and a stored `router = "jev"` or unknown value reads as `act`. The replay harness keeps a Jev fake only as a tripwire, so a stray hop to the retired endpoint fails the fixture.

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

11. Live background agents over ACP (#241, `docs/plans/2026-10-28-2249-feat-wisp-acp-agents-plan.md`): OpenCode helpers run as long-lived ACP sessions through pinned, SHA-256-verified ori and OpenCode 2.x in a private Wisp-owned OpenCode home, with live progress, spoken asks for risky steps within a fail-closed policy, follow-ups, cancel, Wisp tools and memory over an MCP bridge, and onboarding that installs the runtime and stores the OpenRouter key without omaseal. The agent now asks before running tests after it wrote executable files (#265).
12. Verified install and update (#256, `docs/plans/2026-10-29-2302-feat-verified-install-update-plan.md`): a shared preflight for install, update and doctor; `wispd update` backs up, verifies every installed file against the release and records its tag; `--rollback` keeps user edits and restores failed updates. First-run readiness is validated end to end (#264).
13. Hardening on 2026-10-30: spoken replies, typed answers, notes, agent tasks and dictated text stay off the command line (#252, #253, #255); model and daemon text render as plain text in the Panel (#254); a stale cua socket falls back and media keys go through Omarchy's own controls (#257); Esc while the talk key is held ends the capture and the scribble pad lets go (#258).
14. Phase 5, PR 1 of 2 (#261, `docs/plans/2026-10-30-1200-refactor-remove-jev-router-plan.md`): replay fixtures no longer script Jev implicitly; 36 run on the act router and 7 answer-lane fixtures pin `router = chat`.

Also: CI flake root causes (#142), "open my email" opens Gmail when the mail handler is a browser (#147), Argus pinned at c701b2a (#151), act no longer ends a run on a narrated next step without a tool call (#153). Voice polish leftovers (B8b): captions toggle, mic failover, muted speaker keeps the answer on the clipboard, and no announcements on calls. Watchable browser lane (B14): an extension pairs with a code and works in a tab group in your own browser, off by default.  3D parts (B13): an answer can carry one small allow-listed glTF model whose parts you click to ask about.

## Shipped 2026-10-31 to 2026-11-02

Merged after rc.2: #273, #274 and #283-#305. None of it is in a tagged release yet.

1. **Phase 5 PR 2 (#284):** the Jev router is gone from `wisp/`: `route.decide`, the `router = jev` branch, the clarify prompt, `JEV_QUESTIONS` and the Jev-pinned fixtures. Phase 5 is done.
2. **Reply language (#286, TLY-448):** the act loop applies `lang.reply_rule`, so a non-English turn on the default router is told to reply in that language. The `lang_*` fixtures no longer pin `router = chat`.
3. **Default brain (#299):** `openrouter:google/gemini-2.5-flash`, and gpt-4.1-mini is priced. The owner's fallback is openai/gpt-4.1-mini, but the shipped `[brain] fallback` stays empty.
4. **Gauntlet v1** (`docs/plans/2026-11-01-0008-feat-wisp-gauntlet-v1-plan.md`; #290, #291, #297, #300-#305): a gauntlet mode in dev runs, a driver and a case battery. Cases run per session, a skip has a reason, wisp's own policy blocks are removed from gauntlet runs, and wisp's own overlay is not counted as a layer over the click. Results are in `docs/research/2026-11-02-gauntlet-reruns.md`, run on gemini-2.5-flash. Both arms scored 7/12 on the tuning cases. Held-out was 5/7 on clean master, then 4/7 and 2/7 after the click guard. The gauntlet is a diagnostic proxy, not the v1 gate.
5. **Isolated Hyprland session (#295):** a separate session with instance-scoped input, so gauntlet and probe runs do not touch the owner's desktop. It is also U1-U3 of the grounding post-training plan.
6. **Click grounding (#292, #298):** clicks land where aimed on mixed-scale layouts, and fractional or loosely labelled point replies are accepted.
7. **Hermetic tests (#296, #304):** host-env tests and refreshed snapshot goldens, then a hermetic environment for the whole suite.
8. **Settings window, step one (#288):** type scale and settings schema metadata (UI overhaul PR 1 of 7).
9. **Terminal output and TUI (#276-#279):** a shared output core, `wispd doctor` leads with the verdict, the onboarding checklist and installer step output. PRs 1 to 5 of 9.
10. **Site and brand:** a playable desktop with drawings (#273), the `/light/` preview (#274) and its real-time orb (#283, #285), and the flame 3D asset (#293). The site flame hero, #306, is open with changes requested.
11. **Docs and plans:** safety-gate, RC update and CI findings from the master review (#281), multi-OS prep notes, parked (#282), the UI overhaul plan (#287), the grounding post-training plan (#294), and the stable-release gate restored (#289).

## Shipped in #259 (v1.0.0-rc.1) and the RC2 follow-ups

Merged 2026-10-30. The descriptions below were written while #259 was open and are kept as its record; where they say "not verified" or "needs live evaluation", that is still true. RC2 added checksums for the two native attestation sidecars (#262) and the site's guided RC2 install and onboarding (#263).

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
- **Release-completion work in progress:** complete extracted-archive installs, versioned one-line bootstrap, onboarding and attributable plugin/unit recovery; element-backed click provenance and an honest accuracy-data importer; a public growth snapshot and an opt-in local weekly recap. Completion requires integrated tests and independent source review, not only implementation reports.

## Next, in order

Owner's delivery order: installable app first, owner-labelled runs second, measured tuning third. A release candidate is not a waiver or a pass of the stable-v1 gate.

1. **Land the open fixes and rerun the gauntlet.** Merge #307 (F1-F12 and Delete keys), #308 (act prompt: Enter after single-line typing, verify once) and #310 (`[eval] since` gate window; act results say "Dry run" when nothing ran). Then rerun the gauntlet on the isolated session and record the result next to `docs/research/2026-11-02-gauntlet-reruns.md`.
   - **Choose the click finder (owner, TLY-450/TLY-451).** Click probe, 9 known targets per monitor, isolated session, 2026-11-01 to 2026-11-03: local `qwen2.5vl:3b` 7/9 and 6/9 (median miss 31-35 px, but about 30 s per click on CPU); hosted `llama-4-maverick` 4/9 and 6/9 (49-58 px); hosted `gemini-2.5-flash` 2/9 and 3/9 (102-140 px); base `lfm3-vl:2b` 0/9 grounded, because wisp cannot yet read its `[x, y]` 0-1000 answers. On 2026-11-03 the owner set every model to hosted for now, which makes clicks fast but the least accurate; local is the accurate option once it is fast. Ollama's arm64 Linux build is CPU-only, so the Apple GPU (Vulkan, Honeykrisp) is unused (TLY-485).
   - **The owner's own config was wrong for real turns,** fixed 2026-11-03: `[cua] dry_run` was on, so clicks and typing never happened while the model reported them done, and `[ground] providers` was `a11y,jev` with the retired Jev endpoint. Now `dry_run = "false"` and `control,a11y,vlm`.
2. **Owner reinstall from `master`,** and the real compositor and voice checks that tests cannot do: drawing, pointing, rings, arrows, highlights, guided steps, the interactive voice test, and the update/rollback smoke test in `docs/INSTALL.md`'s release checklist.
3. **Owner-labelled real turns, to 50 or more at 60%.** Run a varied set of real tasks across apps and label them with the rating controls, `wispd dev review` and `wispd eval`. Judge output is not an owner label. The owner chose to count only turns from the shipped build: `[eval] since = "2026-11-03"` (#310). The 35 older labels (26%) stay on disk as history.
4. **Clean-box `wispd onboard` and `wispd doctor`** on an Omarchy box with hosted keys only. Where to run it is deferred by the owner until the accuracy gate is closer.
5. **Tag `v1.0.0`.** An `rc.3` first is optional, if the owner wants a prerelease of what is on `master` now. The tag only follows the gates below.

After v1:

- Debug suite (TLY-484): one opt-in switch that keeps a local, per-user record of every model call (brain, answers, grounding, speech, judge: model, prompt, reply, tokens, cost, latency) and every tool call, including OpenCode helpers. OpenCode needs no fork: its 2.x plugin hooks (`session` context and model-request hooks, `tool` execute before/after, the event stream) cover it, installed in Wisp's private OpenCode home. Brainstorm, then plan.
- Local models on the Apple GPU (TLY-485), then teach wisp LFM-VL as the local click finder (grounding post-training below, TLY-451).
- Grounding post-training (`docs/plans/2026-11-01-1139-feat-wisp-grounding-posttrain-plan.md`): U1-U3 are done in #295, U4-U12 are open. It ends in a measurement; switching the default grounding model is a separate decision.
- UI overhaul (`docs/plans/2026-10-31-1754-feat-wisp-ui-overhaul-plan.md`): PR 1 of 7 is merged (#288), PRs 2-7 are open. Terminal output and TUI PRs 6-9 belong here too.
- Multi-OS and the Rust core: parked until the Omarchy v1 gate passes (`docs/research/2026-10-31-multi-os-prep.md`, #282).
- Model learning, only after clean outcome labels, safety review and a held-out evaluation exist. The removed training stack is not coming back for this.
- Interactive scratchpad mini-explainers, richer on-screen 3D, and lightweight macOS/Windows menu-bar companions. Experimental adapters are not supported ports.

`wisp.observer` remains the intended primary domain, not a verified deployment. Stable `v1.0.0` is not yet shipped: only the `v1.0.0-rc.2` prerelease is published, and the gates below decide the final tag.
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

Current tally (`wispd eval`, 2026-11-03): 35 labelled turns, 9 right first time (26%): act 5/22, answer 1/4, launch 1/2, other 2/7. FAIL: the gate needs 60% over at least 50 turns, so at least 15 more labels. Most labels predate the recent fixes, so this understates the current rate.

## Open decisions

- **Q3, the grounding `jev` fallback.** Not decided. The default `[ground] providers` in `wisp/config.py` is still `control,a11y,vlm,uitars,jev`, so `jev` is in the default chain. `JEV_ENDPOINT`, `_jev_locate` and the health `jev` endpoint still exist in `wisp/grounding.py`, `wisp/health.py` and `wisp/config.py`; `wisp/verify.py` only mentions `ask_jev` in comments. The options are to replace the fallback with an OpenRouter vision point call, or to drop it. The frozen Rust daemon (`rs/wispd`) still defaults `router` to `jev` and carries `brain::ask_jev`; that needs a separate parity follow-up.
- **Clacky extras.** Streaming speech-to-text and barge-in shipped (#161, #162). Recommended: drop journaled organize and deferred auth for v1.

## Not doing

- Local-first defaults or automatic local model promotion; explicit opt-in local model servers remain available.
- Model training or distillation in the installable candidate; future learning requires real data and an explicit separate decision.
- Supported full macOS/Windows desktop ports for v1; experimental probe seams are not such ports.
- A decision model (Jev or pplx) in front of routing.
