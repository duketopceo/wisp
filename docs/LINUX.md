# Generic Linux adapter (U9)

Omarchy/Hyprland is the primary target; this adapter makes `dimd`
work on GNOME 48+, KDE/Plasma 5.27+, and X11 sessions through the same
platform seam (`dim/platform.py`, `rs/dimd/src/platform.rs`).

## Detection

`desktop()` probes, in order:

1. `DIMD_DESKTOP` env override (`hyprland|gnome|kde|x11`) — tests and
   forced fallbacks
2. `HYPRLAND_INSTANCE_SIGNATURE` / `hyprctl` on PATH → `hyprland`
3. `XDG_CURRENT_DESKTOP` contains `gnome`/`kde`/`plasma`
4. `DISPLAY` set without `WAYLAND_DISPLAY` → `x11`
5. else `unknown` → Hyprland table (historical default)

## Command matrix

| Capability | Hyprland | KDE | GNOME | X11 |
|---|---|---|---|---|
| screenshot | `grim` | `spectacle -b -n -o` | `gnome-screenshot -f` | `maim` |
| type/dictation | `wtype` | `ydotool type` | `ydotool type` | `xdotool type` |
| focus | `hl.dsp.focus` | `kdotool`/`wmctrl -a` | **unsupported** | `wmctrl -a` |
| close | `window.close` | `wmctrl -c`/`xdotool` | **unsupported** | same |
| workspace | `hl.dsp.focus` | `qdbus KWin setCurrentDesktop` | **unsupported** | `wmctrl -s` |
| launch | `hl.dsp.exec_cmd` | `setsid sh -c` | `setsid sh -c` | `setsid sh -c` |
| monitors | `hyprctl -j` | `xrandr` | none (scale-1 passthrough) | `xrandr` |
| mic/level/TTS/notify | unchanged — `pw-record`/`arecord`, `espeak`, `notify-send` are DE-agnostic | | | |

Every table has a generic PATH fallback order (`grim →
gnome-screenshot → spectacle → maim`, `ydotool → wtype → xdotool`) so
mixed setups still work. Missing tools → `SKIP (… — hint)`.

## Expectations

- **GNOME Wayland intentionally limits** global shortcuts and window
  management — focus/close/workspace SKIP cleanly there. This is a
  platform restriction, not a bug; it's why Omarchy is the primary
  target.
- **Hotkey**: `dimd install` writes Hyprland binds only. On GNOME the
  XDG GlobalShortcuts portal flow is owned by the tray app (U10); on
  KDE/X11 bind `dimd listen` in System Settings / xbindkeys.
- `ydotool` needs the `ydotoold` service (uinput access) — install
  via your distro package.
