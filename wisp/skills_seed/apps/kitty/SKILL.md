---
name: kitty
description: Terminal emulators (kitty, Alacritty, Ghostty, foot) - tabs, splits, copy and paste. Use for teaching a task in a terminal window; not for what to type in a shell.
tier: safe
app_classes: kitty, alacritty, com.mitchellh.ghostty, ghostty, foot, org.codeberg.dnkl.foot, org.omarchy.terminal, xterm
asks: How do I open a new tab; How do I split this window; How do I copy the last output
provenance: authored: wisp seed, audited 2026-11-05
---
# kitty

## Teaching

### Where things live
- There is no toolbar: a terminal is one text area. Everything is a key chord, so name the key and say what it does.
- Tabs and splits exist in kitty and Ghostty only. Alacritty and foot have neither; use a second window or tmux.

### First steps
- Copy is `Ctrl+Shift+C`, paste is `Ctrl+Shift+V`. Bare `Ctrl+C` stops the running program.
- kitty: `Ctrl+Shift+T` new tab, `Ctrl+Shift+Enter` new split, `Ctrl+Shift+Q` close tab.
- Ghostty: `Ctrl+Shift+T` new tab, `Ctrl+Shift+O` split right, `Ctrl+Shift+E` split down.
- Zoom text with `Ctrl+Plus` and `Ctrl+Minus` in Alacritty, Ghostty and foot; kitty uses `Ctrl+Shift+Equal` and `Ctrl+Shift+Minus`.

### Linux pitfalls
- Selecting text already copies it to the primary selection; middle-click pastes it, separate from the `Ctrl+Shift+C` clipboard.
- The terminal shows no controls to point at, so point at the window and speak the key; do not invent a button.
