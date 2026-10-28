# Wisp Roadmap

State: **Phases 1–4, 6, 7 and 8 are on `master`, plus units B1–B34 of the beat-competitors plan except B3, B13, B14 and B31. Next: act quality (Phase 9), then the router fast path (Phase 5).**
Last updated: 2026-10-28. Plan of record: `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md`.

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
9. Beat-competitors plan (`docs/plans/2026-10-27-feat-wisp-beat-competitors-plan.md`), B1–B34 except B3, B13, B14 and B31 (#164–#204): latency gate, earlier first sentence, hand-drawn ink, image cards, walkthrough lessons, scribble to ask, voice speed, document context, named helpers, plan preview, install and trust pages, multilingual turns, dictation safety net, sharing, capture checks, one-instance daemon, self-answers, starter pack, hands-free mode, and a capped trial brain (off).

Also: CI flake root causes (#142), "open my email" opens Gmail when the mail handler is a browser (#147), Argus pinned at c701b2a (#151), act no longer ends a run on a narrated next step without a tool call (#153).

## Next, in order

Each is one PR, planned when it starts.

1. **Phase 9 · Act quality** — fix the top act failures from `wispd eval --misses` (default-app resolution, wrong-coordinate clicks, launch-instead-of-navigate, and claiming success without checking the screen — e.g. "open my Stripe tab" focused the terminal and reported done). Unblocks B3.
2. **Phase 5 · Router fast path** — remove the Jev router (still on the routing path) and its shadow/replay/A-B tooling; the heuristic routes unambiguous launches and questions directly, everything else goes to act. The route span misses its budget (p50 about 1.0 s against 200 ms).
3. **Remaining plan units** — B3 (accuracy loop, after Phase 9), B31 (growth scoreboard), B14 (browser lane, large, off by default), B13 (optional).
4. **Clean-box check** — `wispd onboard` and `wispd doctor` on a clean Omarchy box with hosted keys only.

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
