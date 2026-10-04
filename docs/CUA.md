# Computer use (CUA)

How Wisp clicks, scrolls, types and presses keys for you, end to end:
which backend does it, what stops it, how a name like "night light"
becomes a screen point, and what you see while it happens. Config keys
are in `docs/CONFIG.md`; the Linux capability notes are in
`docs/LINUX.md`.

## The path of one action

```
act loop (wisp/act.py)
  1. observe        grim screenshot, re-taken before every pointer step
  2. ground         target name -> screen point        (wisp/grounding.py)
  3. aim            cua.target event: ghost cursor shows the point
  4. confirm        card, if the tool tier asks         (wisp/confirm.py)
  5. guard          kill, deny, allow, rate, dry run    (wisp/cua_safety.py)
  6. dispatch       one backend, exactly once           (wisp/pointer.py)
  7. audit          one line in cua.jsonl, then click/done events
```

`[pointer] mode` decides whether step 6 injects anything. `guide` (the
default) stops after step 3: the ghost cursor shows the target and you
click. `drive` injects input. `auto` drives when a backend exists and
guides otherwise.

## Pointer registry and precedence

`wisp/pointer.py` holds one backend per injector. In `auto` order:

| Order | Backend | Notes |
|---|---|---|
| 1 | `cua` | background virtual pointer through `cua-driver`; no focus steal |
| 2 | `hyprcursor` | Hyprland cursor move plus a `ydotool` click |
| 3 | `ydotool` | needs `ydotoold` |
| 4 | `wlrctl` | wlroots virtual pointer |
| 5 | `guide` | never injects; the ghost cursor shows the target |

`[pointer] backend` resolves like this:

- `auto` (or any unknown value): the first available backend in order.
- a name (`cua`, `hyprcursor`, `ydotool`, `wlrctl`): that backend only.
  If it is unavailable there is no silent fall-through; Wisp guides.
- `none`: guide mode.

Two rules never change:

- A move is idempotent and falls through: a failed cua move tries the
  Hyprland socket, then the next backend.
- A click is never retried on another backend (double-click risk). A
  failed click is reported and the act loop re-observes.

A cancelled turn raises before any call and during one. It is never a
failure to fall back from. Coordinates are logical Hyprland desktop
coordinates; no backend rescales them.

## cua-driver: install and health

The driver is `trycua/cua`'s `cua-driver`, pinned in `scripts/cua/PIN`
(version, per-architecture URL and archive checksum).

```sh
wispd install --cua --dry-run   # print the plan, touch nothing
wispd install --cua             # download, verify sha256, install, enable the unit
```

`scripts/cua/install.sh` refuses a checksum mismatch before anything is
written, installs the binary at `~/.local/share/cua-driver/cua-driver`
(user scope, no sudo, idempotent), links it into `~/.local/bin`, and
writes `cua-driver.service` (`CUA_DRIVER_RS_ENABLE_WAYLAND=1`,
`Slice=session.slice` so systemd-oomd does not pick it, `MemoryMax=512M`).

`wispd cua status` classifies the driver. It is read only: it looks for
the binary, connects to the socket (nothing is sent) and runs
`cua-driver --version` at most once per binary.

| State | Meaning | Fix shown |
|---|---|---|
| `absent` | no `cua-driver` on `PATH` | `wispd install --cua` |
| `installed_not_running` | binary, no socket | `systemctl --user start cua-driver.service` |
| `socket_unresponsive` | socket file, connection refused | `systemctl --user restart cua-driver.service` |
| `version_mismatch` | running version differs from the pin | reinstall the pinned version |
| `kill_switch_on` | running, kill switch armed (ok, on purpose) | `wispd cua resume` |
| `dry_run` | running, `[cua] dry_run` on (ok, on purpose) | none |
| `running` | healthy | none |

Driver faults outrank the safety modes: a kill switch on a dead driver
still reads as a dead driver. `wispd cua test` is the shorter check of the
binary and the socket. `wispd cua enable` and `wispd cua disable` switch
`[pointer] backend` to or from `cua` (config only; they never start the
driver).

## Safety policy and audit

Every injected call passes `wisp/cua_safety.py`. The order is fixed and the
first match wins:

1. **cancel**: the turn was stopped; raises, nothing is sent.
2. **kill**: `[cua] kill_switch` is on, or the file
   `$XDG_RUNTIME_DIR/wisp/cua.kill` exists. Refused.
3. **deny**: the focused window class matches the built-in deny list or
   `[cua] deny`. Refused.
4. **allow**: `[cua] allow` is set and the app is not on it. Refused, and
   an unknown window fails closed.
5. **rate**: more than `[cua] max_clicks_per_min` counted calls in a
   rolling 60 seconds, or more than `[cua] max_per_turn` in one act run.
   Refused. Moves are gated but not counted.
6. **dry run**: `[cua] dry_run` returns `DRYRUN ...` and invokes nothing.
7. **dispatch**: the backend runs once. A failed click is not retried.

The built-in deny list covers password managers (1Password, Bitwarden,
KeePassXC, Enpass, LastPass), keyrings and prompts (seahorse,
gnome-keyring, pinentry, polkit, kwallet, gcr-prompter, omaseal) and
terminals whose title shows `sudo`. Deny beats allow.

Switches:

```sh
wispd cua kill      # arm the kill switch now (a runtime file; no config edit)
wispd cua resume    # clear it
```

`[cua] confirm = "tier"` keeps the normal tool tiers; `"always"` makes
click, move, scroll, type and key ask once per (tool, focused app) for the
session. `[cua] safety = "false"` turns the layer off, and `wispd doctor`
prints `SAFETY OFF` when it is.

**Audit.** One JSON line per call in
`$XDG_STATE_HOME/wisp/cua.jsonl` (`~/.local/state/wisp/cua.jsonl`):
`ts`, `turn`, `tool`, `app`, `decision` (allow, deny, dry_run, cancelled),
`dry_run`, the first word of the result, and `ms`. Coordinate targets add
`x` and `y`; named keys and chords add `key`; typed text adds only `len`
and `sha`, a 12 hex digit hash with a per-process salt, so repeats match
within a run but cannot be looked up in a dictionary. Typed text, target
names, screenshots and result text are never written. An audit failure
never breaks an action.

```sh
wispd cua log --audit -n 20     # last 20 audit lines
wispd cua log -n 50             # the driver journal
```

The management app's Audit view shows the same log.

## Grounding: from a name to a point

`wisp/grounding.py` turns a click or move target into a point. Providers
run in the order `[ground] providers` gives (default `a11y,uitars,jev`):

| Provider | What it uses | Notes |
|---|---|---|
| `a11y` | the cua `get_window_state` element tree | exact, no pixels; used when the driver is up |
| `uitars` | local UI-TARS on `127.0.0.1:8081` | loopback only; screenshots never leave the machine |
| `jev` | the Decision Agent vision fallback | slowest; has its own `[ground] fallback_timeout_ms` |

The fast providers share `[ground] budget_ms` (default 1200). Each
provider returns nothing (not found), is skipped (not applicable) or is
down (unreachable); nothing else reaches the act loop. The result is one
`Target(x, y, frame, confidence, source)`.

A candidate under `[ground] min_confidence` (default 0.5) triggers
exactly one re-observe: a fresh capture and the whole chain again. If it
is still low the target is refused (`ground_failed`, shown as "couldn't
find that on screen"). A low-confidence point is never clicked. If every
provider is down the error is `ground_down` ("screen grounding is
offline").

**Frame math.** Models answer in the frame of the image they saw, so
every candidate carries a frame and is converted to compositor-global
logical pixels, the same space Hyprland and cua use:

| Frame | Meaning | Conversion |
|---|---|---|
| `global`, `logical` | already compositor-global | identity |
| `canvas` | normalised logical image plus an origin | add the layout bounding box origin |
| `shot` | grim canvas pixels | divide by the scale, then add the origin |

For `shot`, a capture of one output uses that monitor's scale and origin.
A whole-layout capture is composited by grim at the highest output scale,
so the divisor is the largest monitor scale and the origin is the layout
bounding box. Images sent to a model are capped at `[ground] max_side`
(default 1280 pixels on the long side) so the model's coordinates map back
exactly. `[ground] uitars_coords` is `px` or `rel1000` for UI-TARS output.
`[ground] a11y_frame` says whether element frames are `global` or
`window` relative.

## What you see: ghost cursor, confirm card, Esc

**Ghost cursor.** For every click or move the act loop emits a
`cua.target` event (`docs/IPC_CONTRACT.md`) on the push stream:
`{x, y, window, label, confidence, phase}`. `phase` is `aim` once the
point is resolved (the ghost travels there and parks, with a label such
as "night light"), `click` (one ripple at the tip) and `done` (the click
landed; the ghost dims and returns). A failed, refused or dry-run click
sends a clear. The reader only applies the event while the status is
acting, deciding or awaiting a choice, and drops it when the turn ends or
the daemon goes offline. In guide mode the `aim` stays parked on the
target for you to click. Your real pointer does not move for cua clicks.

**Confirm card.** A risky step (a mutating tool, any `shell` or `key`
call, or every input tool under `[cua] confirm = "always"`) publishes
`confirm = {prompt_id, prompt, timeout_s}` and the status becomes
`awaiting_choice`. The companion draws "needs your ok" with allow and deny
buttons. A reply with another prompt id is refused, so a late click cannot
approve the wrong thing. No answer inside `[agent] confirm_timeout`
seconds (default 120, clamped 5 to 600) counts as deny, decided in the
daemon. One yes covers that tool in that app for the session.

**Esc stops it.** While a turn is acting or waiting, Wisp enters a
Hyprland submap named `wisp`: `Esc` stops the turn, `Enter` picks the
first option of a confirm (the yes), and `1` to `9` pick that option.
`Esc` runs `wisp/fastkey.py`, which sends the same IPC `interrupt` as
`wispd interrupt` in about 20 ms. The pointer backends never take focus,
so `Esc` stays reachable while cua acts. The agent's own `key` steps run
outside the submap, so a scripted `Esc` cannot stop its own turn. The stop
control on the console and `wispd interrupt` do the same thing.

## Config keys

All under `[cua]` unless noted. Defaults are in `docs/CONFIG.md`.

| Key | Default | What it does |
|---|---|---|
| `[pointer] mode` | `guide` | `guide`, `drive` or `auto` |
| `[pointer] backend` | `auto` | `auto`, `cua`, `hyprcursor`, `ydotool`, `wlrctl` or `none` |
| `[cua] timeout_ms` | `800` | per call driver timeout |
| `[cua] safety` | `true` | master switch for the guard |
| `[cua] allow` | empty | window class substrings; others are refused |
| `[cua] deny` | empty | extra substrings to refuse |
| `[cua] max_clicks_per_min` | `30` | rolling 60 second cap |
| `[cua] max_per_turn` | `12` | cap per act run |
| `[cua] dry_run` | `false` | plan and log without acting |
| `[cua] kill_switch` | `false` | refuse everything |
| `[cua] confirm` | `tier` | `tier` or `always` |
| `[cua] audit` | `true` | write `cua.jsonl` |
| `[ground] providers` | `a11y,uitars,jev` | chain order |
| `[ground] min_confidence` | `0.5` | below this, re-observe once, then refuse |
| `[ground] budget_ms` | `1200` | shared budget for the fast providers |
| `[ground] fallback_timeout_ms` | `5000` | timeout for the vision fallback |
| `[agent] confirm_timeout` | `120` | seconds before a confirm denies |
| `[keys] submap` | `true` | the Esc, Enter and number key submap |

Change them live with `wispd config set cua.dry_run true`. The Panel
Settings tab edits the same keys.

## Troubleshooting with `wispd doctor`

The pointer section of `wispd doctor` is the first place to look:

```
pointer:
  ok    pointer backend  cua
  ok    pointer mode     drive
  ok    cua driver       running
  ok    cua version      0.33.1 (pin 0.33.1)
  ok    cua safety       safety on, kill off, dry-run off, 30/min, 12/turn
  ok    cua audit log    /home/you/.local/state/wisp/cua.jsonl (649KB)
```

| Line | Meaning and fix |
|---|---|
| `MISS  cua driver  not installed: wispd install --cua` | the binary is absent. Only a failure when `[pointer] backend = "cua"` |
| `MISS  cua driver  installed not running: systemctl --user start cua-driver.service` | no socket. Start the unit, then `wispd cua status` |
| `MISS  cua driver  socket unresponsive: ...restart cua-driver.service` | stale socket. Restart the unit |
| `MISS  cua version  ... (pin 0.33.1)` | the installed driver differs from `scripts/cua/PIN`. Run `wispd install --cua` |
| `cua safety  KILL SWITCH ON` | an armed kill switch. `wispd cua resume` clears it |
| `MISS  cua safety  SAFETY OFF, ...` | `[cua] safety` is `false`. Set it back to `true` |
| `pointer backend  hyprcursor` with the driver up | `[pointer] backend` pins another backend, or the cua plugin is missing. Set `backend = "auto"` |
| `pointer mode  guide` | Wisp points but never clicks. Set `[pointer] mode` to `drive` or `auto` |

Other symptoms:

- **Every click says `REFUSED`**: read the reason. `kill switch` means run
  `wispd cua resume`; `deny` or `allow` names the window class (check
  `wispd cua log --audit`); `rate` means the per minute or per turn cap was
  hit. Raise `[cua] max_clicks_per_min` or `[cua] max_per_turn` only if the
  task is legitimately that long.
- **Clicks say `DRYRUN`**: `[cua] dry_run` is on.
- **"couldn't find that on screen"**: grounding refused a low-confidence
  target. Check that the UI-TARS endpoint is up (`wispd health`), or lower
  `[ground] min_confidence` knowing that it allows weaker guesses.
- **"screen grounding is offline"**: every provider was unreachable. Start
  the endpoints with `wispd health start --run`.
- **Clicks land in the wrong place on a scaled or multi-monitor setup**:
  check `[ground] a11y_frame` and `[ground] uitars_coords`, and confirm the
  monitor scales with `hyprctl monitors`. Frame handling is in the table
  above.
- **The ghost cursor shows but nothing is clicked**: the mode is `guide`,
  or the backend is unavailable. See the doctor lines.
- **`Esc` does nothing**: the submap is not registered. Run `wispd binds`
  and `wispd onboard --step keybinding`. If a `wisp` submap already holds
  binds that are not Wisp's, Wisp refuses to overwrite it and runs voice
  and mouse only; the conflict is logged in `wispd.log`.
- **The driver keeps dying**: `wispd cua log` shows its journal. The unit
  has `MemoryMax=512M`; check for an out-of-memory kill.
