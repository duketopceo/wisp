# Windows adapter (U8)

`wispd` / `wispd-rs` on Windows: same command surface, same
config/state/trace formats. Every OS shell-out routes through
`dim/platform.py` / `rs/wispd/src/platform.rs`.

## Transport

Windows can't use the unix socket: both cores switch to **TCP
loopback** — the daemon binds `127.0.0.1:<ephemeral>` and writes the
port to the `wispd.sock` path as a plain text file. Clients read the
file, connect, and speak the identical newline-JSON protocol, so
fixture replay and `wispd` CLI work unchanged. (The plan's named-pipe
option was superseded: AF_UNIX-in-std lacks on Rust Windows, and a
named-pipe dependency adds total code for no contract change.)

## Paths

| What | Windows |
|---|---|
| config | `%APPDATA%\wisp\` |
| data | `%LOCALAPPDATA%\wisp\` |
| socket/state (port file) | `%TEMP%\wisp\` |

## Command map

| Capability | Linux | macOS | Windows |
|---|---|---|---|
| mic record | pw-record | afrecord | `sox -t waveaudio` |
| mic level | arecord U8 | sox | `sox -t waveaudio -t u8` |
| screenshot | grim | screencapture | PowerShell `CopyFromScreen` |
| type text | wtype | osascript | PowerShell `SendKeys` |
| TTS | espeak | say | PowerShell SAPI (`voice.cmd` overrides — recommended: SAPI quality is poor) |
| notify | notify-send | osascript | BurntToast → `msg` fallback |
| focus | hl.dsp.focus | `open -a` | `WScript.Shell.AppActivate` |
| close | window.close | Cmd-W | `CloseMainWindow` / `Alt-F4` SendKeys |
| workspace | hl.dsp | Ctrl-n | **unsupported** → graceful SKIP |
| launch | exec_cmd | `sh -c` | `cmd /c start /b` |
| monitors | hyprctl -j | system_profiler | `System.Windows.Forms.Screen` (scale=1) |

Missing tools degrade to `SKIP (… — hint)`; nothing panics.

## Deps

- `powershell` (always present), `sox` for mic capture + level meter
  (`winget install sox` or bundled in U10 installer)
- `BurntToast` module optional for rich notifications

## Service / hotkey

`wispd install` registers `schtasks /tn DimAgent /sc onlogon` instead of
the systemd unit. Push-to-talk hotkey: bind `wispd trigger` via
PowerToys Keyboard Manager, AutoHotkey, or `global-hotkey` in the tray
app (U10 packaging).

## Shell

Same decision as U7: thin native `tray-icon` notification-area item
consuming the existing port-file transport — no Tauri webview at this
stage.

## Known residuals

- Workspace/virtual-desktop switching: coming soon — needs the
  IVirtualDesktopManager COM API; today it's an explicit SKIP
- Monitor scale assumed 1 (DPI-aware monitors): coming soon (U10)
- Defender/AV signing friction: coming soon (U10 packaging)
