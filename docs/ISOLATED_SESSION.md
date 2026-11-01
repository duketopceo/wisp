# Isolated test session

A second, invisible Hyprland instance that the gauntlet and the click
probe can drive without touching the owner's desktop. Its input,
screenshots and windows never reach the live session.

    python scripts/isolated_session.py start     # launch + canary
    python scripts/isolated_session.py status    # JSON; exit 1 when down
    python scripts/isolated_session.py canary    # re-run the input canary
    python scripts/isolated_session.py smoke     # the gate (see below)
    python scripts/isolated_session.py stop      # idempotent

Then drive it:

    python scripts/gauntlet.py --session isolated ...
    python scripts/click_probe.py --session isolated --live ...

Both read the env file `start` wrote (default
`$XDG_STATE_HOME/wisp-isolated/isolated.env`, override with
`--isolated-env` or `WISP_ISOLATED_ENV`) and refuse to run without it.

## What it is

- **Mode: nested-hidden (default).** Hyprland 0.56.2 / aquamarine 0.15.0
  has no `AQ_BACKENDS` (its variables are `AQ_DRM_DEVICES`,
  `AQ_FORCE_LINEAR_BLIT`, `AQ_LIBINPUT_NO_PLUGINS`, `AQ_MGPU_NO_EXPLICIT`,
  `AQ_NO_ATOMIC`, `AQ_NO_KMS_REQUIREMENT`, `AQ_NO_MODIFIERS`); with no
  parent socket it falls to DRM/libseat and aborts with
  `CBackend::create() failed!`. So the instance runs as a client of the
  live compositor: only the Hyprland process gets `WAYLAND_DISPLAY` set to
  the ABSOLUTE live socket. Its window (class `aquamarine`) is found by
  the instance's own pid (never by class) and moved at once, silently, to
  the live special workspace `special:wispisolated`, which nothing
  toggles; the owner's active workspace is unchanged (start fails if it
  changes). `--mode headless` (`AQ_BACKENDS=headless`, no parent socket)
  exists only for a future aquamarine: it is refused unless
  libaquamarine contains `AQ_BACKENDS`. Neither mode tries DRM on
  purpose; nothing starts from a tty; start refuses when the instance
  signature equals the live one.
- **Environment:** the OUTER environment (what the private bus inherits as
  its activation environment) is the instance environment: private
  `XDG_RUNTIME_DIR` (mode 0700, under `/tmp/wi-*`), `WAYLAND_DISPLAY=
  wayland-1` relative to it; `DISPLAY`, the live signature,
  `HYPRLAND_CMD`, `NOTIFY_SOCKET` and the live bus address are dropped;
  `HYPRLAND_NO_SD_VARS=1`, `HYPRLAND_NO_SD_NOTIFY=1`,
  `HYPRLAND_NO_CRASHREPORTER=1`. Config: `scripts/isolated_session/
  hyprland.lua` (xwayland off).
- **Private bus:** `dbus-run-session --config-file=<runtime>/dbus.conf`,
  a minimal config with NO service directories and no includes, so the
  bus can activate nothing (keyring, portals, gvfs). Apps that expect a
  session service (nautilus helpers, say) simply run without it.
- **Browsers** the launcher, sandbox and click probe start use
  `--password-store=basic`, so Chromium never asks a keyring.
- **Outputs:** two headless outputs created with
  `hyprctl output create headless` and shaped like the owner's layout:
  3456x2160 at scale 2 (at 0,0) and 3440x1440 at scale 1 (at 1728,0).
  In nested mode the backend's own output (`WAYLAND-1`) is then disabled.
- **Env file:** signature, wayland display, runtime dir, bus address,
  output names and the live signature the instance must differ from.
  Mode 0600, `KEY=value` lines (shell-sourceable).
- **Stop:** `hl.dispatch(hl.dsp.exit())` on the INSTANCE socket, then, if
  it is still up, SIGTERM/SIGKILL of the process group `start` created
  (verified to be our `dbus-run-session` leader). Never `pkill` by
  pattern.

## The live-session leak (found live, fixed)

The first live run of `canary` opened the marker browser in the instance,
and an "OmaSeal" `gcr-prompter` dialog appeared on the LIVE session,
spawned by the owner's `systemd --user` with the private bus and the
parent socket in its environment. Cause: the private bus inherited the
nested Hyprland's environment (which must point at the live socket), and a
Secret Service request from the browser got bus-activated. The live
systemd environment was unchanged. Fixes: the bus inherits the instance
environment (the absolute live socket reaches only the Hyprland process);
the bus config lists no service dirs; browsers use
`--password-store=basic`. How an activation on the private bus reached
`systemd --user` is not proven offline; the activation-free bus is the
block, and smoke's `bus-no-activation` and `live-clients-unchanged` checks
guard it. `canary` and `smoke` fail if ANY client appears on the live
session after `start` (other than the hidden nested window); they only
report it (class, title, address) and never close or interact with it.
Note this also trips on a window the owner opens meanwhile.

## Input is instance-scoped

With the run-copy key `[dev] isolated_session` on (set by the drivers,
never by an agent: it is a safety key), wisp's input goes only to the
compositor named by `WAYLAND_DISPLAY`:

| Action | Isolated path |
|---|---|
| move, click | the bundled `zwlr_virtual_pointer_v1` client (`wisp/vpointer.py`, stdlib only) |
| scroll | the same client's axis events |
| keys, typing | `wtype` on the instance socket |
| `ydotool`, `cua`, `hyprcursor`, `wlrctl` | **refused** (uinput reaches the whole seat) |

A refused path returns `REFUSED (isolated session: ...)` to the act
loop; there is no fallback to a live-seat injector, and no degrade to
guide mode.

## The canary

`canary` opens a marker window in the instance, clicks its centre
through the virtual-pointer client, then asserts the window saw the
click, the live cursor position did not move and no new client appeared
on the live session since `start`. `start` runs it last, and the drivers run it before
the first case.

## The smoke gate

`smoke` is the first live action of the whole post-training plan.
Nothing else runs live until it passes. It checks: session start (nested-hidden);
the private bus config lists no service dirs; both
modes and scales; `grim -o` on each output is not all black; the
canary; `wtype` reaches only the instance; a sandbox browser and file
manager open on the private bus; no new client on the live session; the owner's `systemctl --user
show-environment` and `wispd.service` state are byte-identical before
and after (R7; dbus-broker mirrors systemd's environment as its
activation environment); and a soak (`--soak-seconds`, default 1800)
during which the instance stays up with both outputs.

If a check fails, the output names it. Fallbacks, in order (KTD5), to be
added only if smoke fails: Hyprland nested in a headless weston, then a
QEMU/KVM guest.

## Offline vs live

Everything above is covered by offline tests with fakes
(`tests/test_isolated_session.py`, `tests/test_vpointer.py`,
`tests/test_isolated_input.py`). The launch flags, the headless output
flow, the `hl.monitor` Lua call and the marker-window probes have not
been run against a real compositor; `smoke` is the live check.

Live smoke command (from the owner's Hyprland session, with its own
`WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR` and `HYPRLAND_INSTANCE_SIGNATURE`):

    python scripts/isolated_session.py smoke --soak-seconds 0

then, once that passes, without `--soak-seconds 0` for the 30-minute soak.
