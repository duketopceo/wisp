# cua-driver session lifecycle + agent cursor (R2 research)

Driver: `cua-driver 0.33.1` (`~/.local/share/cua-driver/cua-driver`, aarch64 ELF),
daemon `cua-driver serve` as `cua-driver.service` (user), socket
`~/.cache/cua-driver/cua-driver.sock`, env `CUA_DRIVER_RS_ENABLE_WAYLAND=1`.
Compositor: Hyprland 0.56.2 Wayland on Asahi, with **`cua-hyprland-plugin.so`
v0.1.0 loaded** (autostart.lua:38, config `plugin.cua.enabled` hyprland.lua:38-42).
All findings below were verified live on 2026-10-04 via `cua-driver call` /
`describe` / `sessions` / `hyprctl layers`, using a temporary `r2-probe` session
(ended and confirmed gone).

## VERDICT (up front)

**Yes — the driver's agent cursor renders natively on this Wayland/Hyprland
setup and can drive a Companion ghost cursor.** It is a compositor-level
layer-shell overlay surface (`hyprctl layers` → namespace `cua-agent-cursor`,
top layer, fullscreen 1728x1080 logical on eDP-1), drawn by Hyprland itself,
independent of the user's real pointer. `set_agent_cursor_enabled` /
`set_agent_cursor_theme` / `set_agent_cursor_motion` / `move_cursor
(scope=window)` all work over the socket today. The caveat that decides the
design: **on Wayland the cursor is composited into every screenshot**
(`get_desktop_state` returns `agent_overlay_capture.status: "not_excluded"` —
the driver says it "cannot leave it out"). On macOS it is excluded; here it is
not. So it can replace the QML ghost visually, but every `get_desktop_state`
the model sees will contain the ghost — either accept that (it marks where the
last action landed) or hide it (`enabled:false`) around captures. The QML
ghost also carries wisp-only payload (element label, confidence chips,
creature design) that `cua.default` cannot express; a custom Lottie theme
(`cursor-theme build/install`) is the only way to reskin.

## Session API lifecycle

| Tool | Behaviour (verified) |
|---|---|
| `start_session` | Optional, idempotent. `{"session":"name"}` → `{active:true, effective_scope:"window", revived:false, session}`. Same label after `end_session` returns `revived:true` (revival only via `start_session`; ordinary actions on an ended label are rejected). `cursor_theme:{theme_id,reduced_motion}` optional to pre-set theme before first show. `capture_scope` is deprecated compat. |
| `end_session` | `{"session":"name"}` → `{active:false}`. Runs cursor/recording/config cleanup exactly once. Idempotent. The session cursor is removed when the session ends. |
| `get_session` | → `{client_kind:"cli", cursor_visible, expires_in_seconds, idle_seconds, implicit, recording_active, session, state:"active", transport:"cli"}`. **Sessions idle-expire: `expires_in_seconds` was 297 (≈300 s sliding TTL) right after activity.** |
| `list_sessions` | Scoped to the *authenticated transport lease* — each `cua-driver call` is a fresh lease, so it returned `{"sessions":[]}` even with live named sessions existing. Use `cua-driver sessions` (CLI) for the daemon-global view. |
| `sessions` (CLI) | Global: `STATE TRANSPORT CLIENT SESSION OWNER IDLE`. Showed `itdirect` (daemon/direct, another persistent client), `r2-probe`, plus other agents' `r3-research`/`r4-research`/`r1probe`. |
| `revoke --session <id>` / `--all` | Deny-only kill switch for live sessions. |

**Cross-transport visibility:** named sessions are daemon-global. A session
label passed in *any* `call` args (`"session":"r2-probe"`) works from a
different `call` process than the one that created it — confirmed. Only
`list_sessions`/`get_session` *enumeration* is lease-scoped; `get_session` by
label worked cross-transport too. This is what makes wisp's
`call`-per-action model viable: pin a label like `wisp` on every call.

**Implicit sessions:** omitting `session` uses the transport lease's implicit
session (dies when the `call` exits). Every session — implicit included —
auto-owns an agent cursor keyed to its id.

## Agent cursor tools

| Tool | Verified behaviour |
|---|---|
| `set_agent_cursor_enabled` | `{session, enabled:bool}` → `{enabled, session}`. Show/hide this session's cursor in the shared overlay. |
| `set_agent_cursor_theme` | `{session, theme_id, reduced_motion:auto|on|off}` → theme echo. `cursor-theme list` → only `["cua.default"]` installed (profile `cua-driver-actions-v2`, v2.0.0, 12 semantic action states). Bad id → `invalid cursor theme id` (clean error). Custom themes: Lottie → `cursor-theme validate/build/install` (local-only workflow, `cua-cursor-theme` helper binary ships alongside). |
| `set_agent_cursor_motion` | Physics: `glide_duration_ms` (0=speed-based), `arc_size`, `arc_flow`, `turn_radius`, `spring`, `start/end_handle`, `dwell_after_click_ms`, `idle_hide_ms` (default 15000 → auto-hide after 15 s idle; 0=never). All nullable/omitted = keep current. |
| `get_agent_cursor_state` | → `{enabled, position:{x,y}, motion{...}, theme{id,profile,reduced_motion,version}, visual_state{frame,phase,requested_action,resolved_action,modifiers,preempted_count}}`. Position is the *logical* destination instantly; the rendered surface glides to it (~1 s observed for a 500px move). `visual_state` exposes semantic playback (idle/loop/actions) — driver actions animate the cursor themselves (AX actions "snap with a brief pulse", pixel actions glide). |
| `move_cursor` | `scope:"window"` (default) = **overlay only, real pointer untouched** — `{delivery.mode:"not_applicable", effect:"unverifiable", route:"synthetic_events"}`. `scope:"desktop"` = moves the real OS pointer via the inject path. `cursor_id` supports multiple cursors per session (default `"default"`). |

### Rendering proof on Hyprland

- `hyprctl layers` shows `cua-agent-cursor` (level 3/top, 0,0 1728x1080) on
  eDP-1 whenever the daemon's overlay is on (it existed before my session —
  one shared surface hosts every session's cursor; multiple sessions draw
  concurrently in it).
- Pixel-verified: `get_desktop_state` PNG at cursor (800,500) contained the
  theme's saturated purple fill (RGB ≈ 221,113,236); after `move_cursor` to
  (300,200) + ~1 s settle, the fill was at the new point and gone from the old
  — the cursor *glides* on screen and is captured in screenshots.
- Coordinate space = logical desktop points (1728x1080 @ scale 2), same frame
  wisp already uses (`Coordinate space: logical`, pointer.py).

### Gotchas

1. **In-capture pollution** (`agent_overlay_capture: not_excluded`) — see
   VERDICT. `idle_hide_ms` doesn't help: it's still in the frame while shown.
2. **~300 s idle TTL** — a long pause between wisp turns can expire the
   session and its cursor. `start_session` is idempotent/cheap; re-apply
   theme/motion/enabled on `revived:true`.
3. **`get_cursor_position` returns `"source":"synthetic"`** — on Wayland the
   driver cannot read the user's real pointer; it reports the driver's own
   virtual pointer. Do not use it to correlate with the human cursor.
4. **`effect:"unverifiable"`** on `move_cursor` — fire-and-forget; read back
   via `get_agent_cursor_state` if needed.
5. Overlay is **daemon-global ON by default** (`serve` without `--no-overlay`,
   ours has it). Any session wisp creates already owns a cursor; disabling per
   session = `set_agent_cursor_enabled false`. Daemon-wide flags
   (`--no-overlay`, `--cursor-theme`, `--cursor-reduced-motion`) are serve-time
   only — changing them means editing `cua-driver.service`.
6. Overlay needs the daemon UI runloop — only `serve`/`mcp` hosts own it; the
   `call` CLI is just a client (fine for wisp).
7. `cursor_visible:false` seen in `get_session` while enabled+drawn — treat
   that field as "forced-visible action state", not literal paint status.

## `parallel_mouse_drag`

Schema: ≥2 drags, each `{session, window_id, button, path|fn|from/to, duration_ms,
steps, samples}` — each drag runs on **its own session-scoped virtual master
pointer**, one held press→glide→release (not click chains). Path: segment,
waypoint list, or `fn` y(x) expressions over a domain.

**It is XI2/MPX on X11 and refuses on this Wayland config.** Live result:

    parallel_mouse_drag requires the cua-compositor inject socket on Wayland
    (set CUA_INJECT_SOCKET to the cua-compositor control socket), or run the
    target under X11.

- The binary's Wayland path is "multi-cursor via cua-compositor" (≤4
  concurrent drags), gated on `CUA_INJECT_SOCKET` in the **daemon's** env —
  checked before window validation (bogus window_id still got this refusal),
  and setting it on the `call` client does nothing (env isn't forwarded).
- The socket EXISTS: `cua-hyprland-plugin` created
  `/run/user/1000/hypr/$HYPRLAND_INSTANCE_SIGNATURE/cua-inject-v2.sock`
  (+ `cua-input-v3*.sock`). `HYPRLAND_INSTANCE_SIGNATURE` and `XDG_RUNTIME_DIR`
  are already in the daemon's env — the plugin socket just isn't exported as
  `CUA_INJECT_SOCKET`. Enabling it = ExecStart wrapper resolving the path at
  runtime (persistent change — flagged, not done).
- Not tested past the refusal (would inject real input).
- Note: the `wayland-helper/` dir in the install tree is the GNOME Shell
  extension (`winrects@cua`) — irrelevant here; Hyprland is served by the
  loaded plugin instead (README: wlroots-style path via
  foreign-toplevel/virtual-pointer/layer-shell).

## Wire-up list (wisp files)

Emitter/stream side (the ghost's current feed — `cua.target` event):
- `wisp/grounding.py:693` `emit_target()` — emits aim/click/done/clear.
- `wisp/act.py` — call sites ~L281-388 (`_emit`/aim→click→done, clear on
  fail/refuse/dry-run), `_publish_guide()` L526 (guide-state ghost parking).
- `wisp/state.py` L62,94-99,151,262 — `guide` dict + named-event plumbing.
- `docs/IPC_CONTRACT.md` "cua.target" section — contract to update.
- `shell-plugin/lib/state.js` L106-249 (`view.cuaTarget`),
  `shell-plugin/WispService.qml` L52-55,203, `OverlayLayer.qml` L109-125,
  `GhostCursor.qml` (+ `lib/cursor.js`, `metrics.js`, `motion.js`) — the QML
  ghost that would shrink to label/chip-only or be removed.

Driver-facing side (where the new calls land):
- `wisp/cua.py` — `Cua.call()` L75, `click()` L114 (`scope:"desktop"`),
  `move_cursor()` L119 (`scope:"desktop"` → real pointer). Add: `"session"`
  label on all args; `start_session`/`end_session` lifecycle helpers;
  `set_agent_cursor_*` wrappers; `move_cursor(scope="window")` for
  overlay-only moves.
- `wisp/pointer.py` — `CuaBackend` L78-118 (backend selection/moves),
  `GuideBackend` L171 (guide mode = ghost-for-user-handoff — maps to
  enabled+move_cursor window-scope).
- `wisp/config.py`, `rs/wispd/src/config.rs` — new knobs (session label,
  theme, motion, "driver ghost vs QML ghost" switch).
- `~/.config/systemd/user/cua-driver.service` — only if daemon-wide overlay
  flags or `CUA_INJECT_SOCKET` change (out of wisp repo; manual step).
- `wisp/tui.py` L110 — guide display stays either way.

## Recommended shape

1. Keep a fixed session label (`wisp`) on every cua call; `start_session` at
   act-loop entry (idempotent, sets theme), `end_session` on exit; re-issue on
   `revived` after idle expiry.
2. For aim: `move_cursor` `scope:"window"` (overlay, real pointer stays) +
   keep `set_agent_cursor_enabled true`. Driver actions then animate click
   states on the same cursor for free.
3. Decide the screenshot trade-off: leave the ghost in captures (self-consistent:
   model sees where it acted) or hide around `get_desktop_state`.
4. Keep the QML `GhostCursor` only if wisp's element labels/confidence chips
   matter — or port them to a custom `.cua-theme` later. A hybrid (driver
   cursor for the pointer, QML for labels) is possible since they're separate
   surfaces.
5. `parallel_mouse_drag` stays unusable until the daemon gets
   `CUA_INJECT_SOCKET` — separate follow-up if multi-pointer gestures matter.
