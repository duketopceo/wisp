# Wisp Roadmap

State: **Phases 1–4, 6, 7 and 8 are on `master`, plus units B1–B34 of the beat-competitors plan except B3 and B31. Phase 9 and Phase 5 are partly shipped, and the bar, rating, Dev tab and voice work (phases A to D) is on `master` (below); what is left needs labelled turns or the Jev router deletion.**
Last updated: 2026-10-29 (night). Plan of record: `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md`. This is the only roadmap; `docs/ROADMAP.md` points here.

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

Also: CI flake root causes (#142), "open my email" opens Gmail when the mail handler is a browser (#147), Argus pinned at c701b2a (#151), act no longer ends a run on a narrated next step without a tool call (#153). Voice polish leftovers (B8b): captions toggle, mic failover, muted speaker keeps the answer on the clipboard, and no announcements on calls. Watchable browser lane (B14): an extension pairs with a code and works in a tab group in your own browser, off by default.  3D parts (B13): an answer can carry one small allow-listed glTF model whose parts you click to ask about.

## Next, in order

Each is one PR, planned when it starts.

1. **Phase 9 · Act quality** — shipped so far: default-app resolution (#147), open-tab switching and no unconfirmed success claims (#212), "go to a site" opens in the user's browser instead of `xdg-open` (#231), and clicks that land off every monitor are refused so the loop re-aims (#232). Left: re-rank from `wispd eval --misses` once there are labelled act turns after the verification ladder (none are recorded yet, so wrong-coordinate clicks have no fresh data). Unblocks B3.
2. **Phase 5 · Router fast path** — shipped so far: the regex fast path in front of act (#233; bare launches of catalogued apps and plain questions skip the act loop, `[brain] fast_path`), removal of the shadow decider (#234), the flash lane and the route A/B log (#235), and the fixture migration: the replay harness no longer pins `router = jev`, 43 of the 47 turn fixtures that scripted Jev now run on the default act router (the five `lang_*` and two `answer_*` fixtures that test the answer lane pin `router = chat`), and `choose`, `jev_down`, `jev_slow` and `stale_choice` plus a handful of tests pin `router = jev` explicitly, so those are exactly what the deletion removes. Left, as the next PR: delete the Jev router itself (`router = jev` and the `route.decide` branch of `route_stage`, the clarify prompt, `JEV_QUESTIONS`/`build_questions`, `FakeJev` as a router fake, and the pinned fixtures and tests), normalising a stored `router = jev` to `act`. `ask_jev` stays for now because `suggest` calls it, and the grounding `jev` fallback stays: both wait on Q3, which is still open. Found on the way: the act loop does not add the reply-language rule that the answer lane adds, so a non-English turn on the default router is not told to reply in that language. Plan: `docs/plans/2026-10-30-1200-refactor-remove-jev-router-plan.md`.
3. **Live background agents (#241)** — background agents on OpenCode become live sessions: progress you can see, spoken asks before risky steps, follow-ups, cancel and resume, and onboarding that installs the pinned runtime. Open for review.
4. **Verified install and update** (`docs/plans/2026-10-29-2302-feat-verified-install-update-plan.md`) — shipped so far: a shared preflight, a backed-up and verified `wispd update` with `--rollback`, and the stage and recovery docs. Left: a one-line bootstrap (needs an independently distributed signing key), recovery of the plugin, units and bind, first-install recovery, cleanup tooling, and the local-model promotion gate (waits on #239 and owner thresholds).
5. **Remaining plan units** — B3 (accuracy loop, after Phase 9), B31 (growth scoreboard).
6. **Clean-box check** — `wispd onboard` and `wispd doctor` on a clean Omarchy box with hosted keys only.

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
