# macOS adapter (U7)

`dimd-rs` runs on macOS with the same Unix-socket contract — same
commands, same `state.json`/trace/decisions formats, same TOML config.
Only the platform layer swaps: every OS shell-out routes through
`dim/platform.py` / `rs/dimd/src/platform.rs`, detected at runtime
(`DIMD_OS` env override mirrors it for tests).

## Paths

| What | macOS |
|---|---|
| config + data | `~/Library/Application Support/dim-agent/` |
| socket + state | `$TMPDIR/dim-agent/` (`dimd.sock`, `state.json`) |

## Command map

| Capability | Linux | macOS |
|---|---|---|
| mic record | `pw-record` → `arecord` | `afrecord` (built-in) → brew `sox` |
| mic level meter | `arecord` U8 stream | brew `sox` (absent → level stays 0) |
| screenshot | `grim` | `screencapture -x` |
| type text | `wtype` | `osascript` System Events keystroke |
| TTS | `espeak(-ng)` / `voice.cmd` | `say` / `voice.cmd` |
| notify | `notify-send` | `osascript display notification` |
| focus app | hyprctl eval `hl.dsp.focus` | `open -a <app>` |
| close window | `hl.dsp.window.close` | Cmd-W via System Events |
| workspace | `hl.dsp.focus{workspace}` | Ctrl-‹n› key codes (Mission Control) |
| launch | `hl.dsp.exec_cmd` | `sh -c` |
| monitors | `hyprctl monitors -j` | `system_profiler SPDisplaysDataType` (approx) |

Everything degrades gracefully: a missing binary or unsupported op
returns `SKIP (… — <hint>)`, never a panic. `missing_deps_hint()`
tells the user exactly what's needed.

## Permissions (document, degrade, never crash)

- **Screen Recording** — `screencapture` produces a blank/denied
  image when ungranted; screenshot-dependent features (`screen` tool,
  point overlay context) skip cleanly. Grant in System Settings →
  Privacy & Security → Screen Recording for the terminal/launcher app.
- **Accessibility** — `osascript` System Events keystrokes (dictation,
  `type_text`, Cmd-W close, workspace switch) silently no-op without
  it. Grant for the terminal/launcher app.
- **Microphone** — `afrecord` fails fast when ungranted → the turn
  ends with a "no recorder" error line, logged to the trace.

## Push-to-talk hotkey

`dimd install` only writes Hyprland binds on Linux. On macOS bind
`dimd listen` (or the trigger script) via SKHD, Raycast, Hammerspoon,
or a Shortcuts/Automator global shortcut. Native `global-hotkey`
integration is a U10 packaging concern.

## Shell decision (spike result)

**Thin native menu-bar item + panel** beats a Tauri v2 webview orb for
U7 scope: the existing socket contract already serves a QML shell on
Linux, and the smallest macOS surface is an `NSStatusItem`/`tray-icon`
that reads the same socket and shells out `dimd listen`. A full Tauri
shell duplicates the GUI tab work for ~zero user value pre-release;
revisit if the orb needs to be a floating always-on-top panel (then
Tauri is the pragmatic pick).

## Known residuals

- Monitor geometry via `system_profiler` approximates Retina scale;
  AX/NSScreen (`core-graphics` crate) is the precise path for
  multi-display point mapping.
- `active_window` context is Hyprland-only for now; macOS equivalent
  is `osascript` frontmost-app (follow-up).
- Windows commands are stubs returning `None`/empty — U8 fills them.
- Codesign/notarize/tray bundle: U10.
