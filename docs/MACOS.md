# macOS: experimental adapters — supported arm64 DMG release

Linux with Omarchy/Hyprland remains the full-app target; macOS is the first
supported cross-OS release artifact: an Apple Silicon (arm64) `.dmg`
(`docs/plans/2026-11-23-0014-feat-wisp-macos-arm64-dmg-plan.md`, U6).

## Implemented seams

`wisp/platform.py` contains command builders for capture, transcription
input, notifications, speech, focus, and monitor discovery (macOS: `screencapture`,
`osascript`, `sox`, `say`).
`rs/wispd/src/platform.rs` contains the Rust-side platform mapping.
The Python command builders support `WISP_OS=macos` for deterministic tests
(`tests/test_platform.py`), plus macOS argv contracts in
`tests/test_macos_packaging.py` / `tests/test_macos_dmg.py`.

The local IPC implementation has a Unix-socket transport seam. Requests
without verified peer credentials are refused before dispatch.

## Validation

Deterministic, CI-asserted (`macos-15` in `.github/workflows/release.yml`,
job `mac-dmg`): the full unit suite, arm64 asserts (`lipo`/`file`), packaging
and DMG script contracts (`tests/test_macos_packaging.py`,
`tests/test_macos_dmg.py`, `tests/test_macos_workflow.py`).

Still requires a maintained Mac (per-release, opt-in):

- Screen Recording, Microphone, and Accessibility permissions.
- Recording, level metering, capture, speech, and focus with real tools.
- Browser-profile targeting, action execution, and sensitive-action gates.
- A native hotkey and companion integration, with usable cancellation.
- Installation, background service registration, removal, and upgrades.
- Hardware/model-backed latency and task-success evaluations.

Release process: `scripts/release/macos.py --build`, then `scripts/release/dmg.sh
build` (sign + notarize) and `scripts/release/dmg.sh verify`.

## Source checks

Run the platform and IPC tests from the repository root:

```sh
PYTHONPATH=tests python3 -m unittest test_platform test_ipc_tcp -v
```

These tests check deterministic contracts only. Live macOS gates are not in CI
by design.
