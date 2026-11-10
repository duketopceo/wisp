---
name: omarchy-bridge
description: Where Omarchy things live on this machine — skills, plugins, config, machine stash — so requests like "open my omarchy skills" or "the omarchy bar plugin" resolve to real paths
tier: safe
---
# omarchy-bridge

Omarchy map for this host (Asahi ARM). Use when a request
mentions omarchy, omarchy skills, omarchy plugins, the bar, hyprland
config, or omarchy settings.

- **Agent skill:** `~/.agents/skills/omarchy/` (symlinked into luke-agents)
- **Custom plugins repo:** `~/Documents/github/personal/omarchy-plugins`
- **Installed shell plugins:** `~/.config/omarchy/plugins/` — includes
  `io.github.duketopceo.wisp`, `dayflow`, `omaseal`, `numbat`,
  `bumblebee`, `pplx`, `omasettings`, `tray`, `notification-center`
- **User config:** `~/.config/hypr/*.lua` (Lua, not conf), `~/.config/omarchy/`
- **Machine stash (canonical):** `~/.local/share/machine/<host>/` —
  edit stash first, sync-watch reverts `~/.config/hypr/` otherwise
- **Package-owned (never edit):** `/usr/share/omarchy/`
- **Shell logs:** `/run/user/1000/quickshell/by-id/*/log.log`
- Reload after hypr edits: `hyprctl reload && hyprctl configerrors`
