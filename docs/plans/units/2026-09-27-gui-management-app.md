---
plan: dim-gui-management-app
created: 2026-09-27
status: ready
origin: shells/debug/shell.qml evolution + review residuals
issue: https://github.com/duketopceo/wisp/issues/18
wave: 2
---

# Wisp management GUI — depth pass

## Scope

The Quickshell app ("Wisp" in the launcher) is the real management
surface. Landed: status, logs w/ per-stage timing bars, session,
corrections, tasks, editable settings, memory/skills views, daemon
lifecycle controls. This unit adds the "graphs and visuals" layer.

## Steps

1. **Historical graphs**: persist per-stage timings to a small sqlite
   table (or derive from decisions.jsonl) → Charts in QML
   (Canvas/ChartView): latency-over-time per stage, route mix donut,
   error rate sparkline. Roll-up windows (1h/24h/7d).
2. **Skills tab promoted**: list skills with tier badges, view SKILL.md,
   trigger a `learn` command from the UI.
3. **Memory editor**: edit MEMORY.md/USER.md inline (bounded, atomic
   write via `memory` tool IPC, not raw file writes).
4. **Tasks tab**: spawn a background agent task from the UI
   (name + prompt fields → `agent` route or dedicated IPC cmd);
   cancel buttons wired to `task_cancel`.
5. **Onboarding states**: first-run wizard — API key entry (writes
   `.env` via config IPC), whisper binary check, hotkey confirmation.
6. **Polish**: busy guards everywhere (done), empty-state copy,
   window size persistence.

## Tests

- QML loads clean (existing smoke: `qs -c dim-debug` + `hyprctl
  clients`).
- Graph data path: seed decisions.jsonl → aggregates render.
- Config set via UI round-trips and survives restart.

## Risks

- QML charting is hand-rolled (no QtCharts in Quickshell by default) —
  keep visuals Canvas-based and simple.
- Cross-shell GUIs (GNOME/Win/Mac) are per-wave concerns; this doc is
  Omarchy-only.

## Done when

Opening "Wisp" shows trend graphs, editable memory, skill management,
and task spawning without touching the CLI.
