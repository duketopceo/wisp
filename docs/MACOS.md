# macOS: experimental adapters

Linux with Omarchy/Hyprland remains the full-app target. macOS has
experimental command adapters and a Rust platform seam, not a verified
end-to-end desktop port.

## Implemented seams

`wisp/platform.py` contains command builders for capture, transcription
input, notifications, speech, focus, and monitor discovery.
`rs/wispd/src/platform.rs` contains the Rust-side platform mapping.
The Python command builders support `WISP_OS=macos` for deterministic tests.
Passing command-construction tests does not prove macOS permissions,
installed dependencies, or real device behavior.

The local IPC implementation has a Unix-socket transport seam. Requests
without verified peer credentials are refused before dispatch; transport
existence alone does not establish a usable authenticated macOS control
interface or parity with the Linux companion.

## Validation still required

- Screen Recording, Microphone, and Accessibility permissions on a real Mac.
- Recording, level metering, capture, speech, and focus with actual tools.
- Browser-profile targeting, action execution, and sensitive-action gates.
- A native hotkey and companion integration, with usable cancellation.
- Installation, background service registration, removal, and upgrades.
- Hardware/model-backed latency and task-success evaluations.

There is no release claim here for a macOS installer, launch agent,
tray app, or complete GUI. Do not run the Linux installation instructions
expecting a supported Mac installation.

## Source checks

Run the platform and IPC tests from the repository root:

```sh
PYTHONPATH=tests python3 -m unittest test_platform test_ipc_tcp -v
```

These tests check deterministic contracts only. Linux release and live-run
gates are tracked separately in `ROADMAP.md`.
