# Generic Linux adapter (U9)

Omarchy/Hyprland is the primary target; this adapter makes `wispd`
work on GNOME 48+, KDE/Plasma 5.27+, and X11 sessions through the same
platform seam (`dim/platform.py`, `rs/wispd/src/platform.rs`).

## Detection

`desktop()` probes, in order:

1. `WISP_DESKTOP` env override (`hyprland|gnome|kde|x11`) — tests and
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
- **Hotkey**: `wispd install` writes Hyprland binds only. On GNOME the
  XDG GlobalShortcuts portal flow is owned by the tray app (U10); on
  KDE/X11 bind `wispd listen` in System Settings / xbindkeys.
- `ydotool` needs the `ydotoold` service (uinput access) — install
  via your distro package.

## Pointer backends and cua-driver (W8)

`wisp/pointer.py` holds one backend object per injector, in auto order
`cua > hyprcursor > ydotool > wlrctl > guide`. `[pointer] backend`
pins one (an unavailable pin means guide mode, never a silent switch).
A failed move falls through (cua, Hyprland socket eval, next backend);
a failed click is reported and never retried elsewhere. `[cua]
timeout_ms` (default 800) bounds each driver call.

`wisp/cua.py` wraps `cua-driver call <tool> '<json>'` with argv only (no
shell). It does not speak the daemon socket directly: the socket carries
an internal session protocol with no documented framing, while the CLI
is the supported surface. Errors: `E_CUA_DOWN` (tool_failed),
`E_CUA_TIMEOUT` (timeout), `E_CUA_REFUSED` (tool_failed),
`E_CUA_PROTOCOL` (tool_failed); a cancelled turn raises `Cancelled`.

### Capability spike (cua-driver 0.33.1, read-only)

Sources: `cua-driver --help`, strings of the installed binary and the
bundled docs. No tool was called against the live daemon, so argument
schemas for tools wisp does not use yet are unverified.

| Question | Finding |
|---|---|
| Window-scoped clicks | Yes. `click({pid, x, y})` and `click({pid, element_token})` target a window or accessibility element; `window_id` is accepted. Desktop clicks use `coordinate_frame`/`scope` as wisp sends today. |
| Key and type | Yes. `type_text({pid, window_id, x, y, text})` and `hotkey({pid, keys: [...]})`. |
| Scroll, drag | Yes. `scroll` and `drag({pid, from_x, from_y, to_x, to_y})`, `double_click`, `right_click`. |
| Window tree | Yes. `list_windows`, `list_apps` and `get_window_state({pid, window_id})` returning `tree_markdown`, indexed elements with frames, and an optional screenshot. `verify_state` checks postconditions. |
| Socket protocol | Internal (JSON-RPC style session with `session_begin`); `call` takes `--socket` to pick the daemon and exits 1 on a tool error. |

Consequence for W13: grounding can prefer `get_window_state` over pixels
for apps with an accessibility tree, falling back to UI-TARS. `Cua`
already exposes `list_windows()` and `window_state(pid, window_id)`.
