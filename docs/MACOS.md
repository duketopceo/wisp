# macOS adapter (U7)

`wispd-rs` runs on macOS with the same Unix-socket contract — same
commands, same `state.json`/trace/decisions formats, same TOML config.
Only the platform layer swaps: every OS shell-out routes through
`wisp/platform.py` / `rs/wispd/src/platform.rs`, detected at runtime
(`WISP_OS` env override mirrors it for tests).

## Status

**Linux is the primary platform.** The v1.0 soak, the Omarchy shell
plugin, and the packaged surface are Linux-only; nothing here changes
Linux behaviour, and the Linux command tables are asserted unchanged.

macOS is a supported second platform: the Rust daemon runs the full
pipeline there, the app catalog is populated from `/Applications`, and
the `[apps]` defaults are written per-OS at config time. CI runs the
suite on `ubuntu-latest` **and** `macos-latest`, so a Linux-only
assumption now fails the build instead of rotting silently.

Verified on macOS 27.0 (arm64):

- 253 Python + 25 Rust tests green, including under a stripped PATH with
  no brew, `sox`, whisper, or `hyprctl` present.
- `wispd install` writes a launchd agent that starts, binds its socket
  and answers `wispd status`.
- `pipeline.transcribe()` returns a correct transcript via `whisper.cpp`.
- The app catalog resolves 118 apps; all six semantic keys (`terminal`,
  `files`, `browser`, `settings`, `vscode`, `music`) resolve to a
  launchable command.

## Paths

| What | macOS |
|---|---|
| config + data | `~/Library/Application Support/wisp/` |
| socket + state | `$TMPDIR/wisp/` (`wispd.sock`, `state.json`) |

## Command map

| Capability | Linux | macOS |
|---|---|---|
| mic record | `pw-record` → `arecord` | brew `sox` (`afrecord` is **not** present on macOS 27 — the code probes for it and falls through) |
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
- **Microphone** — with no recorder available the turn ends with a "no
  recorder" error line, logged to the trace. Install `sox` (`brew
  install sox`); macOS ships no `afrecord`. An ungranted Microphone
  permission fails the same way, so check both before debugging deeper.

## Push-to-talk hotkey

`wispd install` only writes Hyprland binds on Linux. On macOS bind
`wispd trigger` (or the trigger script) via SKHD, Raycast, Hammerspoon,
or a Shortcuts/Automator global shortcut. Native `global-hotkey`
integration is a U10 packaging concern.

## Shell decision (spike result)

**Thin native menu-bar item + panel** beats a Tauri v2 webview orb for
U7 scope: the existing socket contract already serves a QML shell on
Linux, and the smallest macOS surface is an `NSStatusItem`/`tray-icon`
that reads the same socket and shells out `wispd trigger`. A full Tauri
shell duplicates the GUI tab work for ~zero user value pre-release;
revisit if the orb needs to be a floating always-on-top panel (then
Tauri is the pragmatic pick).

## Known residuals

- Monitor geometry via `system_profiler` approximates Retina scale;
  precise per-display point mapping via NSScreen: not implemented.
- Codesign/notarize/tray bundle: not implemented (U10 packaging). The
  daemon runs from source; there is no signed `.app` to ship yet.
- No menu-bar surface: the Omarchy shell plugin is QML/Hyprland-only.
  On macOS the daemon is driven by `wispd trigger` from a hotkey binder
  (see above) — there is no equivalent of the Linux bar widget.
- The `[apps]` launch values are single-quoted deliberately: config
  values may not contain `"` (the TOML reader strips surrounding
  quotes), so a bundle name with an apostrophe would need escaping.
