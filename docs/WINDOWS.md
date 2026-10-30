# Windows: experimental adapters

Linux with Omarchy/Hyprland remains the full-app target. Windows has
experimental command adapters and loopback IPC support, not a verified
end-to-end desktop port.

## Implemented seams

`wisp/platform.py` contains Windows command builders and monitor parsing.
`rs/wispd/src/platform.rs` contains the Rust-side platform mapping.
The Python command builders support `WISP_OS=windows` for deterministic
tests. Shell-command construction does not prove that permissions, device
drivers, PowerShell modules, or recording tools work on a real PC.

The experimental IPC seam binds to loopback and writes its selected port
to the socket-path file. TCP does not supply the Linux peer identity
contract, so unattributed requests are refused before dispatch. A usable
authenticated native Windows control interface remains unimplemented;
this is not a complete Windows daemon, companion, or installer.

## Validation still required

- Microphone and screenshot capture, recording dependencies, and permissions.
- DPI-aware monitor coordinates and multi-monitor action targeting.
- Browser-profile targeting, native focus, and reliable cancellation.
- Sensitive-action confirmations and input delivery on a real desktop.
- Native hotkey, companion, background service, installer, and uninstaller.
- Hardware/model-backed latency and task-success evaluations.

There is no release claim here for Scheduled Tasks registration, a tray
app, signing, virtual-desktop support, or a complete GUI. Do not run the
Linux installation instructions expecting a supported Windows installation.

## Source checks

Run the platform and IPC tests from the repository root:

```sh
PYTHONPATH=tests python3 -m unittest test_platform test_ipc_tcp -v
```

These tests check deterministic contracts only. Linux release and live-run
gates are tracked separately in `ROADMAP.md`.
