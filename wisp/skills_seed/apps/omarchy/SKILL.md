---
name: omarchy-app
description: Omarchy desktop — tiling/scrolling layout, workspaces, scratchpads, keybinds, bar plugins, and per-user config detection. Use for window navigation, "go to X app", tiling behavior, keybind questions, and top-bar/plugin questions on an Omarchy host. Not for editing package-owned files under /usr/share/omarchy.
tier: safe
app_classes: hyprland
asks: go to my email; what does Super S do; why did my window disappear; move this window right; what plugins are in my bar
provenance: "authored: user config detection + omarchy defaults 2026-10-31"
draft: first-run (unverified)
---

## Overview

Omarchy is a Hyprland-based desktop. Windows tile by default; this host may run
the `scrolling` layout instead (windows in a horizontal strip per workspace —
navigate with Super+Left/Right, not Super+1..9). The scratchpad is a hidden
workspace (`special:scratchpad`, commonly Super+S) that slides a window in and
out. The top bar is Quickshell plugins under `~/.config/omarchy/plugins/`.

**Load-bearing rule:** user binds in `~/.config/hypr/bindings.lua` override
Omarchy defaults. Before asserting a keybind, check the detected profile
(`scripts/omarchy_profile.py` output or state) — a `hl.unbind` kills the
default and an `o.bind` replaces it. Never quote stock documentation against
the user's actual bind map.

## Screens

- Workspaces 1–N — tiling surfaces; on scrolling layout each is a horizontal strip
- Scratchpad — hidden workspace, slides in over current workspace
- Omarchy menu (Super+Space / Super+K) — launcher + keybindings picker
- Omasettings — settings app for theme/bar/notifications
- Lock screen (hyprlock), notification center plugin, per-app windows

## Controls (defaults — verify against detected profile)

- Super+Arrow — scrolling-layout navigation / directional focus
- Super+1..9 — switch workspace (dwindle); Super+Shift+1..9 moves window
- Super+S — scratchpad toggle (stock; may be remapped)
- Super+W close · Super+V float · Super+F fullscreen
- Super+K keybindings picker · `hyprctl` CLI for everything else

## Workflows

- **"Go to my email"** — detect layout first. Scrolling: Super+Right/Left to
  walk the strip on the current workspace until the mail window is visible;
  dwindle: check workspaces via `hyprctl clients -j` and jump with
  `hyprctl dispatch workspace N` or `focuswindow`. If the browser uses
  vertical tabs, the tab strip is inside the browser window — target it with
  element snapping, not window tiling.
- **"Where did my window go"** — check scratchpad (`hyprctl clients -j` for
  `special:` workspaces) and minimized/floated states before relaunching.
- **New keybind** — append `o.bind` to `~/.config/hypr/bindings.lua`,
  `hyprctl reload`, confirm with `hyprctl binds` or a dry dispatch.

## Tools

- `hyprctl clients -j`, `dispatch`, `binds`, `workspaces`, `monitors`,
  `configerrors`, `reload` — canonical WM control + read-back
- `scripts/omarchy_profile.py` — parses `~/.config/hypr/*.lua` into a JSON
  profile: effective binds (unbind-aware), layout mode, scratchpad binds,
  bar plugins, named app-launch binds
- `~/.config/omarchy/plugins/` — installed bar/shell plugins (detect, don't assume)
- `~/.config/omarchy/omarchy-menu.jsonc` — menu/plugin surface

## Verify before done

- Window navigation: `hyprctl activewindow -j` shows the intended app/class focused
- Keybind claims: the bind exists in the *effective* map (user file beats defaults)
- Plugin claims: directory listing, not memory
- Never edit `/usr/share/omarchy/` — user layer is `~/.config/` only

## Gotchas

- Scrolling vs dwindle changes the navigation verb entirely — detect layout
  from `hyprland.lua`/`looknfeel.lua` before choosing Super+Arrow vs Super+N.
- `hl.unbind` lines mean a default is dead; quoting it is wrong.
- omarchy-menu entry points can be user-forked to `~/.local/bin` paths —
  absolute path in the bind is authoritative.
- Scratchpad windows are invisible on `hyprctl workspaces` until toggled —
  search `clients`, not workspaces.
- unverified — needs a deeper capture: per-plugin bar internals, Omasettings
  screen inventory, hypridle/hyprlock specifics.
