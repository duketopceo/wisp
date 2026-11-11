---
name: dolphin
description: Dolphin file manager (KDE) - location bar, hidden files, split view, terminal panel. Use for teaching file navigation in Dolphin; not for shell file commands.
tier: safe
app_classes: org.kde.dolphin
asks: How do I show hidden files; How do I split the view; How do I open a terminal here
provenance: authored: wisp seed, 2026-11-08
---
# dolphin

## Teaching

### Where things live
- Left: the Places panel (`F9` shows or hides it). Top: toolbar and the breadcrumb location bar, then the file list.
- The menu bar is under the hamburger button when it is hidden.

### First steps
- `Ctrl+L` focuses the location bar so a path can be typed. `Alt+Left`, `Alt+Right` and `Alt+Up` go back, forward and up.
- `Alt+Period` shows or hides hidden files. `Ctrl+Shift+N` new folder, `Ctrl+T` new tab, `F2` rename.
- `F3` splits the view into two panes, handy for copying between folders. `F4` opens a terminal panel at the bottom.

### Linux pitfalls
- `Delete` moves to the Trash; `Shift+Delete` removes for good. Never suggest it as the default way to delete.

## Keyboard routes
- open path: `ctrl+l`, type the full path, `enter`. Only a path the user gave or the window shows.
- go up: `alt+Up`. The title changes to the parent folder.
- new folder: `ctrl+shift+n`, wait for the name field, type the name, `enter`.
- rename: select the item, `F2`, type the new name, `enter`.
