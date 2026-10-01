# feat: Bar plugin full build-out + context-aware act loop + telemetry

## Summary

Turn the bar glyph into a real surface and the agent into a
context-aware companion: (1) a busy-bar/status widget + popout panel
with tabs (live turn, agents, suggestions, log tail, telemetry spark),
(2) the act loop becomes *application-aware* — when you're in Godot and
say "this isn't working", Wisp knows you're in Godot, what the focused
node/panel is, and routes help accordingly; (3) luke-agents skills are
already imported — the GUI must actually show them; (4) heavy local
telemetry — every turn, tool call, model latency, and outcome is
queryable; (5) action-level learning on top of trajectories —
per-action success rates steer future act plans.

## Problem Frame

Today the bar widget is one glyph with a tooltip; the panel is a
transcript readout. Meanwhile `state.json` already carries status,
transcript, choices, tasks, guide, steps — and `wisp/` logs
decisions/trace/trajectories/activity/suggestions. The surface is
behind the data by a mile.

The "context-aware" gap: act loop prompts get skills index + memory,
but not *where you are*. `hyprctl activewindow` + dayflow block +
screenshot give the model the app + title + view — "fix this" in Godot
needs the Godot inspector, not a generic answer.

"RL over actions" is real here only as **credit-assignment over logged
actions**: every act step already records tool+result; scoring each
action's success rate per-app and biasing the planner toward proven
actions is honest learning without pretending to fine-tune weights.

## Requirements

- **R1** BarWidget upgrades: state glyph + live step spinner text
  (current step while busy, e.g. `⣟ click`), suggestion badge dot,
  token/cost ticker optional, right-click record — all themed.
- **R2** Popout Panel becomes tabbed (pattern: dayflow's panel):
  Now (status/transcript/choices/steps) · Agents · Suggest · Log
  (tail of wispd.log + trace.jsonl) · Telemetry (per-route
  counts, model latency, failures).
- **R3** Context injection: every act/answer turn prepends
  `active_window` (app+title) + dayflow current-block label +
  focused-app capabilities card (from skills — e.g. `godot-bridge`
  when focused). `[act] context = "full"|"minimal"|"off"`.
- **R4** GUI Activity tab lists imported luke-agents skills
  (read `~/.local/share/wisp/skills/` — they're on disk, just not
  rendered) + a "used N times / last result" column from
  trajectories.
- **R5** Telemetry: `telemetry.jsonl` — one record per turn:
  {ts, route, model, stt_ms, jev_ms, act_ms, steps, tools_called[],
  outcome, correction?}. `wispd tele` prints a digest; GUI shows a
  24h spark bar + per-route success rate. All local, rotated at 5MB.
- **R6** Action learning: `wisp/action_stats.py` aggregates
  trajectories → per-(app, tool) success rates; act system prompt
  gets a "what works here" block: `in godot: screenshot→click 83%,
  shell 0%`; wrong-branch cautions already exist — extend to
  per-action level.
- **R7** License: MIT — LICENSE file + manifest + README badge
  (needed for open-source release).

## Design / Approach

### U1 — Telemetry writer (`wisp/telemetry.py`)

Single `emit(turn_dict)` called from pipeline.run_turn's finally —
merges the decision record + timing fields into telemetry.jsonl.
Timings: wrap transcribe/ask_jev/act with monotonic stamps (trace.py
already has spans — reuse `_trace.emit` durations rather than a second
clock). Rotation: same pattern as activity.jsonl (rename at 5MB).

### U2 — Context injection (`pipeline.py` + `wisp/context.py`)

`context.snapshot(cfg)` →
`[focus] app=godot title="project.godot — Godot Engine" dayflow="wisp work"`.
Act loop prepends it to the system prompt; answer route appends when
`[agent] screenshots` is already on. Per-app skill match: if a skill
name/description mentions the focused app name, force-include it in
index_text regardless of keyword score (skills already ranked — this
pins them).

### U3 — Bar widget + Panel rebuild (QML)

BarWidget: glyph + optional BusyBar-style 2px progress strip under the
glyph while `busy` (dayflow's BusyBar idiom), badge dot on
`suggestion`/`awaiting_choice`, tooltip gains the current step +
elapsed. Panel.qml: TabBar (Now / Agents / Suggest / Log / Tele) —
Now = current card content; Agents reads `tasks` from state; Suggest
lists `suggestions` via state (already published); Log tails
wispd.log + last 8 trace spans; Tele reads a daemon-published
`state.telemetry` block (per-route counts + last-24h turn count + avg
jev_ms). All themed via theme.json tokens.

### U4 — Action stats + planner bias (`wisp/action_stats.py`)

Scan trajectories.jsonl → `{app: {tool: {ok, fail}}}`. Act loop
system prompt gains a `what works` block for the focused app (top
tools by success rate, flag tools at <40% with ≥3 tries as
"suspect here"). Pure read-time aggregation, ~30 lines.

### U5 — GUI: skills + telemetry views

shells/debug/shell.qml (the debug GUI): Activity tab gets the skills
list (name, tier, tool?, used×, last outcome from trajectories) and a
Telemetry section (per-route counts, today totals). Both read
JSONL files directly — GUI is a file consumer, no new IPC.

### U6 — License + docs

LICENSE MIT, manifest.json license field, README badge, plan/roadmap
touched.

## Acceptance criteria

- Hold Super+D in Godot → orb shows, bar glyph animates a busy strip;
  say "fix this error" → act context includes `focus app=godot` and
  Godot-related skills pinned.
- Panel opens with 5 tabs; Log tab tails the real wispd.log; Tele tab
  shows per-route counts that match `telemetry.jsonl`.
- `wispd tele` prints a 24h digest matching GUI numbers.
- `wispd stats` shows per-(app,tool) rates after ≥3 act runs.
- 230+ tests pass; `wispd install` + restart verified live.

## Risks / mitigations

- **Panel complexity creep** — keep it to five tabs, reuse dayflow's
  BusyBar/pane idioms, no charts beyond a 24-bar spark strip.
- **Telemetry volume** — one line per turn (~300B) ≈ 1MB/3000 turns;
  5MB rotation holds months.
- **Focus privacy** — context reads activewindow only (already
  recorded by sense); nothing new leaves the machine.

## Out of scope

- Model fine-tuning — action-level stats stay prompt-injected.
- Remote telemetry — explicitly local-only.
