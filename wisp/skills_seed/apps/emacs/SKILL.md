---
name: emacs
description: Emacs - M-x commands, buffers, windows, find file, save. Use for teaching editing tasks in Emacs.
tier: safe
app_classes: emacs
asks: How do I open a file; How do I save and quit; How do I split the window
provenance: authored: wisp seed, 2026-11-08
---
# emacs

## Teaching

### Where things live
- Top: menu bar and tool bar (may be hidden). Bottom: the mode line, then the echo area where commands prompt for input.
- `M` means Alt (Meta) and `C` means Control.

### First steps
- `C-x C-f` opens a file; `C-x C-s` saves; `C-x C-c` quits.
- `M-x` runs any command by name; `C-g` cancels a command.
- `C-x 2` splits horizontally, `C-x 3` splits vertically, `C-x 0` closes this window, `C-x o` moves to the other one.
- `C-x b` switches buffer; `C-s` searches forward.

### Pitfalls
- When a prompt appears in the echo area, `C-g` is the way out; the Escape key is easy to misread there.
