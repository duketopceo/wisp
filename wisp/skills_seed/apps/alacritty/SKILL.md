---
name: alacritty
description: Alacritty terminal - copy and paste, scrollback, search, vi mode. Use for teaching a task in an Alacritty window; not for what to type in a shell.
tier: safe
app_classes: alacritty
asks: How do I copy text; How do I search the scrollback; How do I change the font size
provenance: authored: wisp seed, 2026-11-08
---
# alacritty

## Teaching

### Where things live
- There is no toolbar, tab bar or menu: one text area per window. Name the key and say what it does.
- Alacritty has no tabs or splits; use a second window (`Ctrl+Shift+N`) or tmux.
- Settings live in a TOML file, `~/.config/alacritty/alacritty.toml`, not in a dialog.

### First steps
- Copy is `Ctrl+Shift+C`, paste is `Ctrl+Shift+V`. Bare `Ctrl+C` stops the running program.
- `Shift+PageUp` and `Shift+PageDown` scroll the history. `Ctrl+Shift+F` searches forward.
- `Ctrl+Plus`, `Ctrl+Minus` and `Ctrl+0` change and reset the font size.
- `Ctrl+Shift+Space` toggles vi mode, for moving and selecting with the keyboard.

### Linux pitfalls
- Selecting text already copies it to the primary selection; middle-click pastes it.
- Point at the window and speak the key; do not invent a button.
