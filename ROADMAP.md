# Wisp Roadmap

State: **v0.9 released. Wisp is being cut down to HeyClicky for Linux, then made to work end to end on OpenRouter alone.**
Last updated: 2026-10-25. Plan of record: `docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md`.

## Product target

A push-to-talk voice companion for Hyprland/Omarchy. You hold the hotkey and speak. Wisp answers by voice while pointing and drawing on the screen, walks you through multi-step tasks, and runs background agents and routines. Autonomous clicking (act/cua) stays, but it is secondary.

Fixed decisions:

- Local model servers are opt-in and off (`[local] enabled`). OpenRouter is the default backend.
- Linux only. No Windows or macOS port work.
- The training/eval stack goes. One end-to-end eval replaces it as the v1 gate.
- The Rust core in `rs/` is frozen: it stays in the tree with no parity requirement.

## Phases

Each phase is one PR. The plan of record holds the detail, dependencies and sizes.

1. Local models opt-in, act router as the default, unwired lane/grant modules deleted, research docs on master, this roadmap.
2. Salvage the agent substrate from closed PR #138: IPC read/mutate split, truthful task outcomes, CLI and voice-taught routines.
3. Remove Windows/macOS code, tests, CI targets and docs.
4. Remove the training/eval stack and build the end-to-end eval on the turn-replay harness.
5. Remove the Jev decision router and its decisions endpoint.
6. Hosted speech-to-text as the default, a clean-box install, and redeploys from git.
7. Wire the HeyClicky core: walkthrough overlay, drawing, pointing in sync with speech, label-first snapping, per-app history, sensitive-window suppression, streaming speech-to-text.
8. Agent hardening: scrubbed spawn environment, deferred auth, journaled organize with undo, skills export.
9. Act quality fixes driven by the labelled failures.

## v1.0 gate

- [ ] At least 50 labelled end-to-end turns on an OpenRouter-only config, scored by `wispd eval`, at a correct rate the owner sets.
- [ ] `wispd onboard` and `wispd doctor` pass on a clean Omarchy box with no local services and no `~/src/whisper.cpp`.
- [ ] Every module under `wisp/` has a production caller or is gone.
- [ ] Tag `v1.0.0`.

Current state (`wispd eval`, 2026-10-26): 19 labelled turns, 32% right first time — act 27% (3 of 11), answer 0 of 2, launch 1 of 2; 8 turns needed a retry.

## Not doing

- Local-first operation, local model ladders or backend toggles.
- Model training, distillation or per-route soak tooling.
- Cross-platform ports.
- Rebasing onto clacky's codebase. Wisp takes its patterns, not its code.
