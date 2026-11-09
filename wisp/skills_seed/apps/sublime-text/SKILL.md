---
name: sublime-text
description: Sublime Text - command palette, goto anything, multiple selections, project folders. Use for teaching editing tasks in Sublime Text.
tier: safe
app_classes: sublime_text
asks: How do I open the command palette; How do I jump to a file; How do I edit several lines at once
provenance: authored: wisp seed, 2026-11-08
---
# sublime-text

## Teaching

### Where things live
- Top: the menu bar. Left: the sidebar with project folders (View, Side Bar toggles it). Bottom: the status bar with syntax and indentation.
- Preferences, Settings opens the settings file.

### First steps
- `Ctrl+Shift+P` opens the command palette; `Ctrl+P` is Goto Anything for files.
- `Ctrl+R` jumps to a symbol; `Ctrl+G` jumps to a line number.
- `Ctrl+D` selects the next match of the current word; `Ctrl+Shift+L` splits a selection into one cursor per line.
- `Ctrl+K` then `Ctrl+B` toggles the sidebar.

### Pitfalls
- Packages are installed through Package Control, which is added from the command palette and is not built in.
