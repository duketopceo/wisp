---
name: hyprland
description: Hyprland window manager shortcuts, workspaces, and Omarchy tiling controls
tier: safe
app_classes: hyprland, org.hyprland
asks: How do I move a window to another workspace; How do I make this window float; Which key opens the terminal
provenance: authored: wisp seed, frontmatter audited 2026-11-05
---
# hyprland

Omarchy/Hyprland window and workspace bindings:
- **Close window:** `Super+W` or `Super+Q`
- **Toggle floating / fullscreen:** `Super+T` (float), `Super+F` (fullscreen)
- **Switch workspace:** `Super+1..0` (stock Omarchy has 10 per monitor), move window with `Super+Shift+1..0`
- **Focus direction:** `Super+Arrow` (stock Omarchy binds `Super+J/K/L` to split, keybindings and layout, not focus)
- **Reload config:** `hyprctl reload && hyprctl configerrors`
