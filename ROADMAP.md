# Wisp Roadmap

State: **v0.9 released. The unified plan (W1 to W29, W32) has landed on master; the v1.0 gate (W34) is the soak, a clean-box install and the learning loop.**
Last updated: 2026-10-04. Plan of record: `docs/plans/2026-10-04-0100-feat-wisp-unified-plan.md`.

## Plans

Read in this order. The roadmap plan is the program-level view (Now, Next, Later, with status and evidence per workstream); the rest are child plans it links by unit.

1. `docs/plans/2026-10-05-001-feat-wisp-full-roadmap-plan.md`: full roadmap, current state and U1 to U12.
2. `docs/plans/2026-10-04-0100-feat-wisp-unified-plan.md`: owner of the W1 to W34 IDs and the crosswalk.
3. `docs/plans/2026-10-02-2315-feat-wisp-ember-redesign-plan.md`: Ember UI redesign, with the per-unit Status Ledger (spec: `DESIGN-v2.md`).
4. `docs/plans/2026-10-03-1455-feat-wisp-backend-core-plan.md`: backend core (StateBus, health, cancel, ledger, replay).
5. `docs/plans/2026-10-03-002-feat-gauntlet-v2-plan.md`: training gauntlet v2 (shipped).
6. `docs/plans/2026-10-04-1800-feat-cua-driver-and-parallel-training-plan.md`: CUA wiring and parallel training.

Progress on the v1.0 gates:

- ✅ U10 merged (PR #31); release CI verified — `v0.9.0` published all
  five platform archives; linux-aarch64 artifact runs the live daemon.
- ✅ Visible surface: bar glyph, companion orb, app menu, GUI — verified.
- ✅ Run labeling landed: `wispd label correct|incorrect` + orb ✓/✗ →
  `labels.jsonl`; `wispd label` prints the per-route intent-match report.
- 🔄 Soak: label every run; fix top failure mode weekly; re-measure.
  Current: 0/1 labeled (0%) — gate needs ≥50 labeled runs per route.
- ⬜ Fresh-box install ≤10 min on a clean Omarchy VM.
- ⬜ Learning loop exercised twice (`wispd learn` → approve → clarify
  rate drops).
- ⬜ Tag `v1.0.0` once the soak gates pass.

Landed on master since v0.9 (unified plan, PRs #55 to #100): computer use as
a subsystem (pointer registry, cua-driver install and health, safety policy
and audit, grounding chain, `docs/CUA.md`); the Ember surfaces (companion,
four-tab Panel, bar mark, confirm card, ghost cursor, keyboard submap with Esc
stop, management app and TUI, first-run card, desktop entry); the backend core
(push stream, one spend ledger with caps, Jev deadline and heuristic router,
batch lane, opt-in GlitchTip reporting, oomd-safe units, `wispd onboard`, the
`wispd <group> <verb>` CLI). Still open: W12 warm STT, W30 pipeline refactor,
W31 contract freeze, and the gate below.

## v1.0 gate checklist (W34)

All four are required. Run them in this order; tick a box only with the
evidence named next to it.

- [ ] **Soak: 50 labelled runs per route, at least 50% intent match per route.**
  Routes: launch, tool, agent, act, answer (dictate and clarify are reported
  but not gated).
  How: use Wisp daily. After each run label it, with the `good` and `wrong`
  buttons or `wispd label set correct` / `wispd label set incorrect`. Read the
  per-route table with `wispd label report` (add `--json` to archive it). Fix
  the top failure mode weekly (`wispd learn fails`, `wispd eval route`,
  `wispd trace digest`), then re-measure. Evidence: the `wispd label report
  --json` output, showing n >= 50 and match >= 0.50 on every gated route,
  pasted into the release notes. The 85% figure in the v1.0 definition below is
  the stretch target; 50% is the gate the unified plan sets for the tag.
- [ ] **Fresh-box install in under 10 minutes via `wispd onboard`.**
  How: on a clean Omarchy VM with nothing of Wisp installed, start a stopwatch
  and run only what `docs/INSTALL.md` says: `git clone`, `python3 wispd
  install`, `systemctl --user enable --now wispd`, `wispd onboard` (every step
  or a deliberate skip), then `wispd doctor` and one spoken turn. Stop when the
  turn gets an answer. Evidence: the elapsed time, the `wispd doctor` output
  (exit 0) and `wispd onboard --status`. Not yet done: needs a VM and a person.
- [ ] **Learning loop exercised twice.**
  How: cycle one: `wispd learn weekly` stages a criteria proposal; review it,
  approve it (merge the edits into `~/.config/wisp/criteria_overrides.json`,
  never automatic), and approve any recipe with `wispd recipes approve <n>`.
  Cycle two: repeat a week later. Evidence: for each cycle the proposal file,
  what was approved, and the clarify rate for the week before and after from
  `wispd trace digest` (it must drop, or the reason it did not is written
  down).
- [ ] **Tag `v1.0.0`.**
  How: when the three boxes above are ticked, the full gate set is green
  (unittest, `snap.py check`, `gen_copy.py --check`, `gen_settings.py
  --check`) and the release workflow builds all five platform archives, tag
  `v1.0.0` with release notes (the soak table, the install time, the two
  learning cycles) and file the Omarchy plugin marketplace verify request.

Also open before the tag (not gating): live screen recordings for the README
(list in `README.md`, section Media), a live latency baseline (W2
`needs_live_baseline`), and the Rust contract freeze (W31).

Shipped beyond the v1.0 gates (post-roadmap work, live on master):

- ✅ Proactive companion (2026-09-30): sense collector reads dayflow +
  hyprctl window deltas into `activity.jsonl`; Jev-gated suggestion
  miner → orb "an idea" cards (automate / not now / never, approval-only);
  `agent_runtime=auto` probing + `wispd doctor`; seeded `dayflow-bridge`
  + `self-checkup` skills; GUI Activity tab; `wispd tui`; task caps,
  timeout reaper, PID-reuse pinning, daily model-call budget.
- ✅ Dual-OS (2026-10-01): macOS is now a supported second platform with
  Linux still primary — host-independent suite, `/Applications` app
  catalog (118 apps), per-OS `[apps]` defaults in **both** the Python and
  Rust config layers, a launchd agent that carries a real `PATH` (without
  it brew's `sox` was invisible), and CI running on `macos-latest`
  alongside `ubuntu-latest` so a Linux-only assumption fails the build.
  `docs/MACOS.md` records what is verified and what is not.
- ✅ Shadow decider (2026-10-02): `[jev] shadow = "pplx"` has a second
  decision model (Perplexity `pplx-decider-v1-27b`) answer the same
  questions on every routed turn, in a background thread, logging both
  answers to `shadow.jsonl` under the same trace turn id that
  `decisions.jsonl` carries. The primary still decides and the turn never
  waits on the shadow. This is the missing half of the accuracy gate: two
  models can now be scored against human labels instead of against each
  other.
- ✅ Conversational agent pass (2026-10-02, PRs #37–#52): Clicky-style
  Talk/Agent split with the screenshot captured at trigger; goal memory
  (`wisp/goals.py`, 10-min TTL) so multi-utterance sequences are one
  task; `ASK_USER:` voice backchannel; confirm-once per (tool, app);
  cursor-adjacent answer bubble + bottom-center listening pill +
  streaming deltas + `wispd interrupt`; Panel v2 (Now/Agents/Activity/
  Tele/Skills/Context/Connect tabs, session strip); `wispd context` +
  `wispd inventory` local-terrain passthrough (apps, CLIs, MCP servers,
  omarchy plugins/binds, dayflow); `mcp_call` tool (streamable-HTTP +
  stdio JSON-RPC); `wispd connect` OAuth via the BrowserOS Strata
  gateway (~45 services); Jev slimmed to route/app/risk/tool;
  recipe graduation — user-labeled multi-step wins draft `recipe-*`
  skill proposals (human-gated via `wispd recipes approve`); soak-gate
  fixes — deterministic re-observe before pointer actions, BrowserOS
  preferred for `browser` when its MCP server is live, natural-language
  workspace args. Plans: `docs/plans/2026-10-02-00{1,2,3}-*`.
- 📋 Planned (2026-09-30): guide cursor (ring + peel-off ghost),
  `click` pointer tool with guide-mode fallback, vision-fed act loop,
  episodic trajectory memory → human-gated recipe skills — **shipped**
  (guide cursor + `click`, vision act loop, trajectories → recipes);
  `docs/plans/2026-09-30-002-feat-wisp-guide-cursor-recipes-plan.md`.

## Where it is

- Pipeline shipped: `Super+D` → PipeWire capture → whisper.cpp (`ggml-small.en`) → Jev routing (`launch | tool | agent | act | dictate | answer | clarify`) → Talk answers w/ `[POINT]` cursor / guarded act loop / agent runtimes (opencode/codex/claude/devin) / `mcp_call` → companion orb, cursor bubble, pill, and panel.
- Units U1–U9 merged: resident daemon, spoken answers (U4), dictation + orb states (U5), semantic recall via sqlite-vec + RRF (U5c), dev trace `trace.jsonl` (U5e), pluggable brain providers — OpenRouter / openai-compat / Ollama / MLX (U6), macOS adapter (U7), Windows adapter (U8), generic-Linux adapter (U9).
- U10 merged (PR #31); release CI verified end-to-end.
- Session memory, weekly human-gated learning loop (`wispd learn`), and answer-route with optional screenshot context all work in code.

**The honest gap:** verified pieces now exist (release binary runs the
daemon, sense collector is recording, labeling is wired), but labeled
volume is 1 run. Reliability is still unmeasured — v1.0 remains a
verification milestone, not a feature milestone.

## v1.0 — "it actually works on my machine"

Definition of done — all required, no substitutes:

1. **U10 merged** and release CI green: binaries for Linux x86_64/aarch64,
   macOS, Windows, published as a tagged release.
2. **A two-week soak with measured success.** Every trigger logged to
   `trace.jsonl` with route + outcome; each run human-labeled correct or
   incorrect. Gate: **≥ 85% intent-match per route** (launch / tool /
   agent / answer) over ≥ 50 labeled runs per route.
3. **Failure budget:** no more than 1 in 20 triggers ends in silence, a wrong
   action, or a daemon crash.
4. **Visible surface, always:** ✦ status glyph live in the Omarchy bar,
   companion orb on screen while listening, `Wisp` in the app menu, and
   the management GUI openable from both — verified after a fresh login,
   not just when launched by hand.
5. **Fresh-box install ≤ 10 minutes** on a clean Omarchy VM, following only
   `docs/INSTALL.md`.
6. **Learning loop exercised twice:** `wispd learn` proposal → human
   approval → measurable clarify-rate drop after each cycle.
7. Tag `v1.0.0` with release notes; marketplace verify request for the
   Omarchy plugin listing.

Order of work: visibility first (landed: real `BarWidget` + `Panel.qml`
popup replacing the wrong-shaped `Panel` root — widget rendered nothing
before) → add run-labeling to trace (small: `wispd label` or a panel
button) → use Wisp daily for two weeks and label every run → fix the top
failure mode each week (expect STT accuracy and Jev routing confidence
first) → re-measure.

## v1.x — depth

- Wake word ("Wisp", openWakeWord) alongside `Super+D`; VAD endpointing
  on top of the toggle capture (landed) so silence auto-stops the mic.
- Whisper upgrade path: `faster-whisper` small → medium on GPU boxes;
  multi-language STT.
- Promote the optional adapters to first-class: dayflow activity mining as
  context, omaseal as the secrets source.
- GUI depth: graphs tab, editable memory, agent task spawn/cancel from the
  panel (exists in the management app unit — polish it).
- Agent lane: named persistent agents that announce progress unprompted.

## v2.0 — the resident OS assistant

- macOS and Windows adapters at v1.0-parity with the Linux surface.
  macOS is now CI-verified and installable from source
  (`docs/MACOS.md`); the remaining gap is the menu-bar surface and a
  signed/notarized bundle.
- Multi-profile (household) support.
- Local-first everything: STT, routing (Ollama), and answers offline by
  default; cloud models as opt-in accelerators.

## Cut list

Anything not required for the soak is cut from v1.0. Wake word, new tools,
and adapter polish wait. The only metric that ships v1.0 is the labeled
success rate.
