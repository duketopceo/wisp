---
name: zed
description: Zed editor - command palette, file finder, multi-cursor, terminal, split panes. Use for teaching editing tasks in Zed.
tier: safe
app_classes: dev.zed.zed
asks: How do I open the command palette; How do I find a file by name; How do I open the terminal
provenance: authored: wisp seed, 2026-11-08
---
# zed

## Teaching

### Where things live
- The left dock holds the project panel; the status bar at the bottom toggles docks and shows the language and cursor.
- Settings open from the application menu, as a JSON file with a default copy beside it.

### First steps
- `Ctrl+Shift+P` opens the command palette; `Ctrl+P` opens the file finder.
- `Ctrl+Shift+F` searches the whole project; `Ctrl+F` searches the current file.
- `Ctrl+B` toggles the left dock; `Ctrl+J` toggles the bottom panel.
- `Ctrl+D` selects the next match of the word under the cursor for multi-cursor edits.

### Pitfalls
- Keymap changes live in the keymap file, not in the settings file; point to the command palette's open keymap action.
