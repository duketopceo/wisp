# Wisp Roadmap

State: **Phases 1–4 are on `master`. Next: put `master` on the desktop, make install and speech-to-text hosted by default, then fix act turns.**
Last updated: 2026-10-26. Plan of record: `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md`.

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

Also: CI flake root causes (#142).

## Next, in order

Each is one PR, planned when it starts.

1. **Redeploy** — install `master` to the desktop and restart `wispd`, so new labels measure current code.
2. **Phase 6 · Hosted install** — hosted speech-to-text default, onboarding asks for keys, `wispd install` redeploys from a git ref, clean-box check.
3. **Phase 9 · Act quality** — fix the top act failures from `wispd eval` (default-app resolution, wrong-coordinate clicks, launch-instead-of-navigate).
4. **Phase 7 · HeyClicky surfaces** — pointing timed to speech, drawing overlay, walkthroughs with label-first snapping, per-app history, sensitive-window skip, streaming speech-to-text, barge-in.
5. **Phase 5 · Router fast path** — remove the Jev router and its shadow/replay/A-B tooling; the heuristic routes unambiguous launches and questions directly, everything else goes to act.
6. **Phase 8 · Agent hardening** — scrub Wisp-held credentials from spawned agents' environment.

## v1.0 gate

- [ ] `wispd eval` passes `[eval] gate_rate` over at least 50 labelled turns.
- [ ] `wispd onboard` and `wispd doctor` pass on a clean Omarchy box with hosted keys only.
- [ ] Tag `v1.0.0`.

Tally (`wispd eval`, 2026-10-26): 19 labelled turns, 6 right first time (32%) — act 3/11 (7 retried), answer 0/2, launch 1/2, other 2/4. Gate not set.

## Open decisions

- **Pass rate.** Recommended: `gate_rate = "60%"` now, raised after Phase 9.
- **Clacky extras.** Recommended: keep streaming speech-to-text and barge-in; drop journaled organize, skills export and deferred auth for v1.

## Not doing

- Local-first operation, local model ladders or backend toggles.
- Model training, distillation or per-route soak tooling.
- Cross-platform ports.
- A decision model (Jev or pplx) in front of routing.
