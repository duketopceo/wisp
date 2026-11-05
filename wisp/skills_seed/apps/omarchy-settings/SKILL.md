---
name: omarchy-settings
description: Omarchy menu and settings - theme, background, bar, monitors, keybindings, network, update. Use for teaching where an Omarchy setting lives; not for editing config files.
tier: safe
app_classes: quickshell, omarchy
asks: How do I change the theme; How do I change the wallpaper; Where do I set up monitors
provenance: authored: wisp seed from the stock omarchy-menu.jsonc item labels, 2026-11-05
draft: first-run (unverified)
---
# omarchy-settings

## Teaching

### Where things live
- There is no settings window. `Super+Space` opens the Omarchy menu: Apps, Learn, Appearance, Trigger, Setup, Install, Remove, Update, About, System. "Settings" is the Setup item.
- Appearance: Theme, Background, Font, Menu Bar (position, background), Windows (gaps, corners, opacity), Workspace Layout, Animations.
- Setup: Monitors, Keybindings, Input, Typing, Language, Network, Defaults, Plugins, Security, Config.
- System: Lock, Suspend, Logout, Reboot, Shutdown. Trigger: Toggle (Stay Awake, Nightlight, Notifications), Capture, Share, Reminder.

### First steps
- Theme: `Super+Ctrl+T` or menu > Appearance > Theme, pick one to apply it. Background: `Super+Ctrl+W`.
- All key bindings, as this machine has them: `Super+K`.
- Updates go through menu > Update (`omarchy update`), which wraps the package manager.

### Linux pitfalls
- The menu is a shell overlay, not a window: it takes no window class, so point at the item by its visible label.
- Files under `/usr/share/omarchy` are replaced by updates; personal changes belong in `~/.config`.
