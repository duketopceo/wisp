---
name: ghostty
description: Ghostty terminal - tabs, splits, copy and paste, config reload. Use for teaching a task in a Ghostty window; not for what to type in a shell.
tier: safe
app_classes: com.mitchellh.ghostty
asks: How do I open a new tab; How do I split the window; How do I reload the config
provenance: authored: wisp seed, 2026-11-08
---
# ghostty

## Teaching

### Where things live
- The window is one text area, with a tab bar that appears once there is more than one tab.
- Settings are a plain text file, `~/.config/ghostty/config`; there is no settings dialog to point at.

### First steps
- Copy is `Ctrl+Shift+C`, paste is `Ctrl+Shift+V`. Bare `Ctrl+C` stops the running program.
- `Ctrl+Shift+T` new tab, `Ctrl+Shift+N` new window, `Ctrl+Shift+W` close the current pane.
- `Ctrl+Shift+O` splits to the right, `Ctrl+Shift+E` splits downward.
- `Ctrl+Shift+Comma` reloads the config after an edit.

### Linux pitfalls
- Selecting text also fills the primary selection; middle-click pastes it, separate from the clipboard.
- Keys can be rebound in the config; if a chord does nothing, check the config first.
