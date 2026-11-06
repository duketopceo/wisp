# Click observation on Hyprland: spike (U4)

Date: 2026-11-05. Machine: Hyprland 0.57.1 (Lua config), Asahi, session user, no root.
Question: how can Wisp learn that the user clicked the control it pointed at,
with no privileges, no input-group change, no `/dev/input` access, and no
restart of anything?

Everything below was read-only. Nothing clicked, typed or moved the pointer, no
Hyprland setting was changed, and no frame was saved (timing captures went to
`/dev/null`).

## Rung (a): a compositor event source

What I ran:

1. Connected to `$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock`
   (the event socket, world-readable, same user) and logged every event name
   for 60 s while polling `cursorpos` every 20 ms alongside it.
2. Listed the event names compiled into the installed `Hyprland` binary
   (`strings`), looking for anything pointer-button shaped.

What it produced:

- In 60 s the pointer position changed 667 times, so a person was using the
  machine. The only events were `screencast`, `screencastv2`, `activewindow`,
  `activewindowv2`, `activelayout` and `closewindow`. No event named for a
  pointer button, press or click appeared.
- The binary's event vocabulary is window, workspace, monitor, layer, group,
  layout, submap, screencast and `custom` events. The strings `button`, `click`
  and `mouse` occur in the binary but none is an `name>>data` event.
- `activewindow` fires when a click moves focus, which says a click happened
  only when the click changed focus. It cannot confirm a click on a control
  inside the already-focused window (the common case), and it cannot say where.

I did not synthesize a click to double check, because the brief forbids input
on the live desktop. The conclusion rests on the 60 s capture plus the event
list, and is consistent with Hyprland's documented events (no pointer-button
event).

Not tried: registering a pass-through mouse bind through the Lua config to get a
callback on button press. It would likely work, but it mutates the live
compositor's input handling (and could swallow clicks), which a read-only,
no-restart spike must not do. Worth a separate, owner-approved experiment.

Verdict: rung (a) does not work unprivileged.

## Rung (b): cursor-position poll plus settle

What I ran:

- `hyprctl cursorpos` and `hypr.query("cursorpos")` (the repo's socket client)
  with no privileges: 20 `hyprctl` runs took 3.0 ms p50 / 8.2 ms max; 50 socket
  queries took 0.03 ms p50 / 0.05 ms p95 / 0.09 ms max.
- `grim -s 0.05 -t ppm -` (whole layout, 5% scale, output discarded): 299 ms p50,
  454 ms max over 8 runs.

What it produced: the pointer position in logical layout pixels, the same
coordinate space Wisp points in, cheaply and unprivileged. It cannot see a
button press. It can see that the pointer is at rest and, with a downsampled
frame diff, that the screen reacted afterwards. A click is therefore inferred:
pointer at rest and the screen changed. Inside the step radius is clicked-in;
elsewhere, after the pointer travelled there, is clicked-out.

Limits, all handled or accepted:

- A click the app shows no reaction to is not seen. The step stays waiting and
  the existing stuck prompt or the user's "continue" covers it.
- A page that animates under a parked pointer could look like a click. A
  reaction with the pointer elsewhere only counts as clicked-out when the
  pointer travelled there, and the baseline frame is retaken each time the
  pointer comes to rest.
- grim costs about 0.3 s, so settle polls at 0.3 s and the click watch only
  grabs frames while the pointer is at rest.

Verdict: works unprivileged.

## Rung (c): voice confirm

Needs nothing. It is also the delivery for any click step when no pointer
source or no frame source exists.

## What ships

Rung (b) (`wisp/click_watch.py`) plus settle (`wisp/settle.py`) plus voice
confirm. Rung (a) was only a probe and has no code in the tree.

Constants and where each came from:

| Constant | Value | Source |
|---|---|---|
| `CLICK_POLL_S` | 0.1 s | cursor query 0.03 ms p50, so bounded by the frame grab |
| `CLICK_REST_S` | 0.2 s | two polls at `CLICK_POLL_S` |
| `SETTLE_POLL_S` | 0.3 s | grim 299 ms p50, 454 ms max |
| `SETTLE_DIFF` | 0.005 | synthetic frames in `tests/test_settle.py`: blinking cursor 0.0007, opening dropdown 0.08 |
| `SETTLE_WINDOW_S` | 0.9 s | three quiet polls at `SETTLE_POLL_S` |
| `HOVER_REST_S` | 0.8 s | GTK's 500 ms tooltip delay plus margin; not measured here |
| `DEFAULT_CLICK_RADIUS` | 30 px | ring in `tests/fixtures/turns/answer_draw_timed.json` |

`SETTLE_DIFF` is a downsampled-synthetic-frame figure, not a live measurement;
it should be re-checked on a real browser session (see the PR checklist).
