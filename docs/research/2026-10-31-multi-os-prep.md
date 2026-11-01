# Multi-OS Wisp: preparation notes (not a plan to build yet)

Date: 2026-10-31. Status: **parked until the Omarchy v1 gate passes.**

This note records what a multi-OS Wisp (other Linux desktops, then
Windows, then macOS) would take, and the decisions to make when it
starts. Nothing here is scheduled. The Omarchy version ships first.

## The gate before any of this starts

No cross-OS feature work until all of these hold (ROADMAP v1 gate, plan
R28):

1. At least 50 owner-labelled turns, at the configured 60%
   first-time-correct gate (`wispd eval`).
2. Clean `wispd onboard` and `wispd doctor` on a fresh Omarchy install
   from a published release candidate.
3. The open safety and release findings are closed (#281 and the
   `pointer.mode` decision).

Until then the only cross-OS work allowed is what keeps the door open
for free: keep new OS-specific calls behind `wisp/platform.py` instead
of calling `hyprctl` or `omarchy-*` inline.

## Where things stand (master 17c3446)

| Piece | Size | Cross-OS today |
|---|---|---|
| Python core (`wisp/`, `wispd`) | ~49k lines | Pipeline, brain, routing, act loop and memory are mostly OS-neutral. |
| Shell UI (`shell-plugin/`, QML/JS) | ~10k lines | Omarchy only. It is a Quickshell plugin inside the Omarchy shell. |
| Rust daemon (`rs/wispd`) | ~5.8k lines | Frozen parity copy of the IPC daemon, kept byte-compatible by `tests/fixtures/ipc_commands.jsonl`. Not the product core. |
| `wisp/platform.py` | seams | Command builders for Linux, `WISP_OS=macos` and `WISP_OS=windows`, tested only as command construction. |
| IPC (`wisp/ipc.py`) | seam | Linux uses `SO_PEERCRED`. TCP and non-Linux sockets refuse every command (`unattributed_peer`). |
| Omarchy coupling | 17 files mention `omarchy`, 16 call `hyprctl` | Concentrated in platform, tools, install and the shell plugin. |

`docs/MACOS.md` and `docs/WINDOWS.md` list what is unverified.

## Three different jobs hide in "multi-OS"

**1. Other Linux desktops (cheapest).** Same Python, same systemd user
units, same packaging. The work is the desktop layer:
- window focus/close/workspace and active-window lookup: today Hyprland
  (`hyprctl`); other compositors need Sway IPC, KDE/GNOME DBus, or X11
  `xdotool`/`wmctrl`;
- the overlay and panel: the Quickshell plugin needs Omarchy's shell.
  A standalone Quickshell overlay works on wlroots compositors (Hyprland,
  Sway, river) but not GNOME, which has no layer-shell;
- input: `ydotool`/cua already work beyond Omarchy.

**2. Windows (largest audience, most new code).** Needs native pieces
Python shells out to poorly: global hotkey, screen capture, input
injection, a click-through overlay, DPI-aware coordinates, an installer
and a background service. IPC needs a named pipe with client process
identity, which is Windows' counterpart of `SO_PEERCRED`, before
`unattributed_peer` can lift.

**3. macOS (smallest audience, most gatekeeping).** Screen Recording,
Microphone and Accessibility permissions (TCC), code signing and
notarization (Apple Developer account), a launch agent, and an overlay
window. Same IPC peer-identity question (`LOCAL_PEERPID`).

## Repo shape: one repo, not a branch per OS

Long-lived OS branches drift: every fix to the brain, routing or safety
gates would need porting to each branch, and the safety gates are where
drift hurts most. Keep one `master`:

- an OS-neutral core: pipeline, brain, routing, policy, memory, eval;
- adapters behind one interface: `linux-omarchy` (today's code),
  `linux-generic`, `windows`, `macos`. `wisp/platform.py` is the start
  of this;
- one shell or UI per desktop family under `shells/` or `shell-plugin/`;
- a CI matrix with one job per OS that runs the core tests everywhere and
  the adapter tests on its own runner;
- per-OS packaging under `scripts/release/` (tar.gz for Linux, MSI or
  MSIX for Windows, a notarized .pkg/.dmg for macOS).

Branches stay short-lived feature branches, as now.

## Rust core or Python core

Options, to decide when the gate passes:

- **A. Keep Python, ship a bundled runtime per OS.** Least new code.
  Distribution is the pain: an embedded interpreter per OS, and slower
  start-up.
- **B. Rewrite the core in Rust.** `rs/wispd` covers the IPC daemon only,
  about an eighth of the Python by size. A rewrite would freeze product
  work for months during the phase where routing and prompts change
  weekly from labelled runs.
- **C. Hybrid (recommended to evaluate first).** Python stays the brain
  and pipeline. A small native helper per OS, likely Rust (`windows-rs`,
  `objc2`), owns what Python does badly: hotkeys, capture, input,
  overlay, and authenticated IPC. It ships as one signed binary per OS.

C keeps tuning speed and puts native code where it pays off. Revisit B
only if the Python core is stable for a quarter and packaging becomes
the bottleneck.

## Decisions for the owner when this starts

1. Which OS first after v1: generic Linux (cheapest, same packaging) or
   Windows (largest audience)?
2. The UI for non-Omarchy desktops: standalone Quickshell (wlroots only),
   Qt/QML packaged per OS, or a web-tech shell (Tauri)?
3. Option A, B or C for the core.
4. Spend: an Apple Developer account for macOS notarization, and a
   Windows code-signing certificate.

## Cheap prep that is allowed now

- New code that needs window, input, capture or desktop calls goes
  through `wisp/platform.py`, not inline `hyprctl` or `omarchy-*`.
- When a module is already being edited, move Omarchy-specific calls
  behind the platform seam. No sweeping refactor before v1.
- Keep `docs/MACOS.md` and `docs/WINDOWS.md` honest about what is
  unverified.
