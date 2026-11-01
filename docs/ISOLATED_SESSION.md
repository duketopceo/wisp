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

- **Backend:** Hyprland with `AQ_BACKENDS=headless`, so it never opens
  DRM. It starts only from a live Wayland session (never from a tty) and
  refuses when its signature equals the live one.
- **Environment:** `DISPLAY`, `WAYLAND_DISPLAY` and the live signature
  are dropped; `HYPRLAND_NO_SD_VARS=1`, `HYPRLAND_NO_SD_NOTIFY=1`; a
  private `XDG_RUNTIME_DIR` (mode 0700) and a private D-Bus from
  `dbus-run-session`; the test-only config
  `scripts/isolated_session/hyprland.lua` (xwayland off).
- **Outputs:** two headless outputs created with
  `hyprctl output create headless` and shaped like the owner's layout:
  3456x2160 at scale 2 (at 0,0) and 3440x1440 at scale 1 (at 1728,0).
- **Env file:** signature, wayland display, runtime dir, bus address,
  output names and the live signature the instance must differ from.
  Mode 0600, `KEY=value` lines (shell-sourceable).

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
on the live session. `start` runs it last, and the drivers run it before
the first case.

## The smoke gate

`smoke` is the first live action of the whole post-training plan.
Nothing else runs live until it passes. It checks: headless start; both
modes and scales; `grim -o` on each output is not all black; the
canary; `wtype` reaches only the instance; a sandbox browser and file
manager open on the private bus; the owner's `systemctl --user
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
