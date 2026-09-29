---
plan: dim-u8-windows-adapter
created: 2026-09-27
status: implemented
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U8
issue: https://github.com/duketopceo/wisp/issues/15
wave: 4
---

# U8 — Windows adapter + tray shell

## Scope

`wispd-rs` on Windows: same command surface over a named pipe, native
adapters.

## Steps

1. **Transport**: `tokio::net::windows::named_pipe` (or std equivalent)
   behind the same newline-JSON protocol — the contract's commands and
   `state.json` schema are unchanged; document the pipe path in the
   contract's transport section.
2. **Adapters**: `enigo` (input), `xcap` WindowsGraphicsCapture,
   `cpal`, SAPI TTS, `global-hotkey`, `tray-icon` notification-area
   item; window ops via `windows-rs` (SetForegroundWindow etc.).
3. **Runtime dirs**: `%APPDATA%/wisp`, `%LOCALAPPDATA%/wisp`;
   same config format.
4. **Shell**: same spike decision as U7 — share whatever wins.
5. **Service**: Task Scheduler registration inside `wispd install`
   (U10 delivers the installer; the registration path is written here).

## Tests

- Named-pipe transport parity test (fixture replay over the pipe).
- `#[cfg(windows)]` adapter unit tests where headless-possible.

## Risks

- Windows Defender/signature friction for the binary — defer to U10.
- First-class TTS quality on SAPI is poor — make `voice_out_cmd` the
  documented escape.

## Done when

Hotkey → transcript → guarded action works on Windows via the same
contract, and the tray app reflects state.
