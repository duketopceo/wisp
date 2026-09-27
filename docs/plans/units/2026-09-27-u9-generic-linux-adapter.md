---
plan: dim-u9-generic-linux
created: 2026-09-27
status: ready
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U9
issue: https://github.com/duketopceo/dim-agent/issues/16
wave: 4
---

# U9 — Generic-Linux adapter (GNOME/KDE, non-Hyprland)

## Scope

Everything is Hyprland-specific today (`hyprctl`, `grim`, `wtype`). This
adapter makes `dimd-rs` work on GNOME 48+ / KDE 5.27+ Wayland and X11
where practical.

## Steps

1. **Compositor detection**: probe `hyprctl`, `gdbus`/portal, X11
   `$DISPLAY` in order; record detected shell in `state.json`.
2. **Hotkey**: `global-hotkey` crate — Wayland via XDG GlobalShortcuts
   portal (GNOME 48+, KDE 5.27+ confirmed), X11 via XRecord path.
3. **Screenshot**: XDG portal screenshot → `gnome-screenshot`/spectacle
   fallback → `grim` if wlroots; keep Hyprland's `grim` fast path.
4. **Input**: `ydotool` (uinput, portal-safe, compositor-agnostic) as
   primary; `wtype` fallback on wlroots.
5. **Window ops**: KWin script/`gdbus` for KDE; GNOME has no general
   window-move API — degrade gracefully (workspace ops only, document
   the gap).
6. **Tray/UI**: AppIndicator (`tray-icon`); the management GUI needs a
   non-Quickshell story on GNOME — candidate: gtk4 window sharing the
   same socket contract (decide at spike).

## Tests

- Adapter selection matrix unit test (fake env vars/PATH).
- Fixture replay passes with the generic adapter.

## Risks

- GNOME intentionally limits global shortcuts/window ops — set
  expectations in docs; this is why Omarchy is the primary target.

## Done when

On a GNOME VM: hotkey works via portal, screenshot arrives, typed text
lands via ydotool.
