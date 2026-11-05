# Generic Linux adapter (U9)

**Status: planned, not yet supported.** Wisp is Omarchy-first: it is
built into Omarchy first (Hyprland on Arch), and other desktops come
later. GNOME, KDE/Plasma and X11 are *planned*, not promised and not
supported today. This page describes the adapter code that exists for
them (it is not tested against real GNOME, KDE or X11 sessions, and no
fix or behaviour on those desktops is guaranteed). Use Omarchy.

The adapter makes `wispd` attempt GNOME 48+, KDE/Plasma 5.27+, and X11
sessions through the same platform seam (`dim/platform.py`,
`rs/wispd/src/platform.rs`).

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
| tab | DevTools `/json/activate` on 127.0.0.1 (9108, 9107, 9222), then `hl.dsp.focus` on the window | tab switches; window not raised | same | same |
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
  KDE/X11 bind `wispd trigger` in System Settings / xbindkeys.
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

## Accessibility snap (AT-SPI)

Teaching and walkthrough pointing snaps the model's point to a real
control: `wisp/elementtree.py` reads the AT-SPI tree and
`walkthrough_run.snap_point` applies it. Order: a label match in the tree
(nearest the model's point when several match), the same label through the
`ground` providers, the smallest control holding the model's point, then the
model's own box. Every step records `snap` (`ax`, `model` or `none`), the
winning rung (`via`), `confidence` and the app name, in the trace
(`snap` event) and in the walkthrough dump.

**Client choice: system GObject introspection, imported lazily.** Install
`python-gobject` and `at-spi2-core` (Arch; `python3-gi` and
`gir1.2-atspi-2.0` on Debian). Wisp keeps no Python runtime dependencies,
so `gi` is looked up only when a snap runs; without it the tree reports
`unavailable` and pointing uses the model box. Direct D-Bus was rejected: it
would re-implement the registry walk, state sets and coordinate types that
Atspi already provides.

**Binding rule.** Wayland clients get no screen coordinates, so extents are
read in window coordinates and moved into the logical global frame by the
focused toplevel's origin from Hyprland. The tree binds only to the ACTIVE
frame of the Hyprland-focused window's application (same pid, else same app
name), or to the single frame whose title matches. A control counts only
inside that toplevel's frame and not under a floating window; containers
(structural roles, or larger than `CONTAINER_FRACTION` of the screen) are
never targets. Anything else falls to the next rung.

**Unavailable is not no-match.** `ax_status` is `ok` (the tree answered),
`unavailable` (no `gi`/Atspi, bus unreachable, compositor query failed) or
`unbound` (AT-SPI is up but no toplevel binds). Unavailable and unbound
snap to the model box with `snap: none`; a tree that answered but had no
match logs `model`. `elementtree.snap_share(records)` reports the
per-app share and counts the two failures apart. The user never sees an
error for either.

**Known limits.** Many Wayland apps publish near-empty trees (GPU-drawn
canvases, terminals, some Electron builds), and a hidden window can keep a
full tree that is not `showing`. A read-only probe on the dev machine bound
the focused window correctly but found few controls in most apps, so the
model box is the common outcome until an app publishes a real tree.
Scaling: extents are taken as logical pixels; an element that overflows its
toplevel (a toolkit reporting physical pixels) fails the frame check and is
skipped.

**Recorded-tree fixtures** (`wisp-elementtree/1`, JSON) let a harness replay
the snap with no desktop. Shape:

```json
{"format": "wisp-elementtree/1", "app": "fixture-settings",
 "state": "ok", "reason": "",
 "windows": [{"title": "main", "frame": [100, 100, 800, 600],
              "focused": true, "above": false,
              "elements": [{"label": "Save", "role": "push button",
                            "rect": [700, 640, 80, 32]}]}]}
```

`rect` and `frame` are `[x, y, w, h]` in logical global pixels; `focused`
marks the toplevel the tree binds to; `above` marks an unfocused window that
covers what lies under it; `state` may be `unavailable` or `unbound` to
replay those cases. `tests/fakes/elementtree.py` serves one as an
`ElementTree`, and `elementtree.load_fixture` validates it. The checked-in
set is drawn by `tests/fixtures/trees/make_trees.py` from invented apps and
labels. Never paste a tree captured from a real session: window titles and
control labels are the user's content.

## Service hygiene (W29)

`scripts/units/*.service` are the templates for `llama-local`, `llama-jev`,
`llama-uitars`, `jev-shim` and `wispd`. `wispd install` (or
`wispd install --units`, preview with `--dry-run`) copies them to
`~/.config/systemd/user/`, backing a changed unit up to
`<unit>.service.bak-<stamp>` first, then runs `daemon-reload` only. It never
enables, starts or restarts a unit, and skips a llama unit whose wrapper is
not installed.

- `Slice=session.slice`: `app.slice` carries `ManagedOOMMemoryPressure=kill`
  and `ManagedOOMSwap=kill`, so a 21G llama server is the oomd's first pick.
  `ManagedOOMPreference=omit` alone does not cover the swap rule (systemd only
  honours it for swap when the cgroup is root-owned), so the slice move is the
  primary fix and `omit` is defence in depth.
- `StartLimitIntervalSec=900`, `StartLimitBurst=30`, `RestartSec` with
  `RestartSteps=5`/`RestartMaxDelaySec=60`: never lands "enabled but dead".
- `wispd.service` is `Type=notify` with `WatchdogSec=60`; the daemon sends
  `READY=1` and `WATCHDOG=1` every 20 s while its IPC server thread is alive.
- `wispd doctor` adds a `services` section: llama unit state, slice, oomd
  preference, and the voxtype `alsa::poll() POLLERR` spin (journal rate or a
  hot `cpal_alsa` thread), with the fix `systemctl --user restart voxtype`.
