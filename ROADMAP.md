# Wisp Roadmap

State: **Phases 1–4 and 6 are on `master`, with the first Phase 7 surfaces (cursor buddy, speech-timed points, on-screen drawing). Next: act quality (Phase 9), then the rest of Phase 7.**
Last updated: 2026-10-27. Plan of record: `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md`.

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

Also: CI flake root causes (#142), "open my email" opens Gmail when the mail handler is a browser (#147), Argus pinned at c701b2a (#151), act no longer ends a run on a narrated next step without a tool call (#153).

## Next, in order

Each is one PR, planned when it starts.

1. **Redeploy** — install `master` to the desktop and restart `wispd`, so new labels measure current code. `wispd install --ref` is the tool; the clean-box check of Phase 6 still needs a run on a clean box.
2. **Phase 9 · Act quality** — fix the top act failures from `wispd eval` (default-app resolution, wrong-coordinate clicks, launch-instead-of-navigate).
3. **Phase 7 · HeyClicky surfaces (remaining)** — walkthroughs with label-first snapping, per-app history, sensitive-window skip, streaming speech-to-text, barge-in.
4. **Phase 5 · Router fast path** — remove the Jev router and its shadow/replay/A-B tooling; the heuristic routes unambiguous launches and questions directly, everything else goes to act.
5. **Phase 8 · Agent hardening** — scrub Wisp-held credentials from spawned agents' environment.

## v1.0 gate

- [ ] `wispd eval` passes `[eval] gate_rate` (`60%`, decided by the owner 2026-10-27) over at least 50 labelled turns.
- [ ] `wispd onboard` and `wispd doctor` pass on a clean Omarchy box with hosted keys only.
- [ ] Tag `v1.0.0`.

Tally (`wispd eval`, 2026-10-26): 19 labelled turns, 6 right first time (32%) — act 3/11 (7 retried), answer 0/2, launch 1/2, other 2/4. Gate set to 60% (needs 31 more labelled turns and a higher rate).

## Open decisions

- **Clacky extras.** Recommended: keep streaming speech-to-text and barge-in; drop journaled organize, skills export and deferred auth for v1.

## Not doing

- Local-first operation, local model ladders or backend toggles.
- Model training, distillation or per-route soak tooling.
- Cross-platform ports.
- A decision model (Jev or pplx) in front of routing.
