---
name: omarchy
description: Teach Omarchy itself (themes, keybindings, tiling, packages, the menu) from this machine's own install, not a copied manual
tier: safe
requires_bin: omarchy
---
# omarchy

Questions about using Omarchy ("how do I change the theme", "split a
window", "install an app", "show every binding") are answered from this
machine, not from memory: wisp reads the `omarchy` command list, your
`bindings.lua`, the current theme and the installed version when you ask,
and adds them to the turn (`wisp/omarchy_tutor.py`).

- Name the key you actually have, from your own bindings.
- Point at the real menu item and put its visible label in the point tag.
- Package commands are offered, never run; read an AUR PKGBUILD first.
