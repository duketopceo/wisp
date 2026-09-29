---
plan: dim-u7-macos-adapter
created: 2026-09-27
status: implemented
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U7
issue: https://github.com/duketopceo/wisp/issues/14
wave: 4
---

# U7 — macOS adapter + tray shell

## Scope

`wispd-rs` runs on macOS: same socket contract (unix socket — macOS has
them), adapters swapped for native crates/APIs.

## Steps

1. **Adapters**: `enigo` (input/type/click), `xcap` ScreenCaptureKit
   path (screenshot), `cpal` (mic in), `say` (TTS), `global-hotkey`
   (Carbon/portal-equivalent), `tray-icon` menu-bar item; window ops via
   AppleScript/AX calls where needed.
2. **Runtime dirs**: macOS paths — `~/Library/Application
   Support/wisp/`, socket in `$TMPDIR`; keep config file format
   identical.
3. **Shell spike**: thin native (`tray-icon` + minimal panel) vs Tauri
   v2 webview orb — pick by smallest total code; both consume the
   socket contract, so the daemon work is done either way.
4. **Permissions**: screen recording + accessibility prompts documented;
   graceful degradation when denied.
5. **Release checklist** (codesign/notarize) captured as docs, code
   lands in U10.

## Tests

- Adapter unit tests behind `#[cfg(target_os = "macos")]`.
- Fixture replay suite passes on macOS.

## Risks

- Accessibility permission UX is the biggest product risk — needs
  human-tested first-run flow.
- Whisper binary: document `whisper.cpp` build or ship a cask-side
  dependency.

## Done when

A real hotkey → transcript → action round-trips on macOS with the
management UI showing live state.
