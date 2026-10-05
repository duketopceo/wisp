# cua-driver 0.33.1 — Tool Surface Catalog (research agent R1)

Probed live on `omarchy-max` (Asahi Linux aarch64, Hyprland 0.56.2, native Wayland,
`CUA_DRIVER_RS_ENABLE_WAYLAND=1`, daemon running as `cua-driver.service`,
socket `~/.cache/cua-driver/cua-driver.sock`). All probes were read-only —
no click/type/key/drag input was injected. `move_cursor` was exercised
once *without* `scope` (synthetic overlay only; the user pointer was
verified unchanged via `hyprctl cursorpos`).

`list-tools` reports **62 tools** (the "~94" estimate in the task brief was
high). Every `describe` output was captured; schema field lists below drop
the ubiquitous optional `session` label unless it is required.

## Headline findings

1. **element_tokens are effectively unavailable on this Wayland session.**
   Apps that publish a real AT-SPI tree (GTK4 Junction: 7 elements;
   Chromium: 124; spotifast: 130) come back `degraded: true` with
   `degraded_reason: accessibility_window_identity_unproven` — the driver
   can walk the app's AT-SPI bus but cannot bind the tree to a specific
   toplevel, so it **withholds `element_token` and `frame` on every
   element** (0 tokens / 0 frames across 124–130-element trees). Apps with
   no AT-SPI (foot, 1Password, Hermes) come back
   `x11_property_fallback_partial` — one degenerate `role:"window"`
   element that *does* carry `element_token: "sNNNNNNNN:0"` but only an
   `activate` action. Net: the token format works (`^s[0-9a-f]{8}:[0-9]+$`)
   but no actionable token is ever issued here. **The whole ax-action rung
   (element_token addressing on click/type_text/set_value/scroll/…) is
   dead on native Wayland 0.33.1; pixel coordinates are the only rung.**
2. **Observation works well.** `get_desktop_state` returns a full-output
   PNG (1728x1080 logical @ scale 2, downsized per `max_image_dimension`)
   plus the on-screen window list. `get_window_state` per-window
   screenshots succeed for live mapped toplevels (foot 3/3, chromium ✓)
   but fail `surface_identity_unproven` for windows Hyprland can't prove
   (e.g. an AT-SPI-registered window absent from `hyprctl clients` —
   Junction failed 3/3). `zoom`, `verify_state`, `get_screen_size`,
   `get_cursor_position`, `list_windows`, `clipboard_read`,
   `health_report` all work.
3. **All clients are native Wayland — zero XWayland** on this system
   (`hyprctl clients -j`: 9/9 `xwayland=false`, including Chromium on
   ozone). Every "X11/XSendEvent" mention in tool descriptions is a
   fallback path that never executes here; the live Wayland input path is
   `zwlr_virtual_pointer` (left-button only, no modifiers) for pointer
   actions and libei + xdg-desktop-portal for `delivery_mode:"background"`
   (injecting at compositor input focus — no per-window background
   targeting; `background_unavailable` when no libei backend).
4. **`get_accessibility_tree` is process-list-only on Wayland** — returns
   918 processes and `windows: []` (its window enumeration is X11-only).
   Use `list_windows`/`get_desktop_state` for window discovery.
5. **State is session-scoped across CLI calls.** Named `session` labels
   (e.g. `"r1probe"`) DO persist snapshot context between separate
   `cua-driver call` processes (zoom worked after a same-label
   get_window_state); capture_ids and implicit sessions do not
   (`capture_not_found`, `screenshot_context_missing` across calls).
   Wisp's per-call `Cua.call` model must pass a stable `session` label to
   use zoom/capture_id/element caches.
6. **Recording is already active** on this daemon (`get_recording_state`:
   `recording: true, owner: "r4s", output_dir: /tmp/cua-rec-sess`) — a
   sibling agent's session. Do not `stop_recording`/`end_session` it.
7. **Browser surface is consent-gated.** `get_browser_state` on a consumer
   Chromium profile refuses cleanly with `browser_consent_required` →
   `browser_prepare` + existing-profile launch grant. `parse_visual_regions`
   returns `not_installed` (optional cua-perception extension).
8. **Cursor reads are per-session.** `get_cursor_position` returns the
   *synthetic* agent cursor (`source:"synthetic"`), and different sessions
   report different positions (implicit session: 836,527; r1probe:
   1500,500 after its own move to 400,300 — `get_agent_cursor_state`
   showed the true r1probe position). The real user pointer is only
   visible via `hyprctl cursorpos` (171,718).

## Support matrix

Legend — wayland status: ✅ verified live · ⚠️ works with caveats ·
❌ fails/blocked · 🔸 untested live (input mutator or state mutator —
schema notes only) · ➖ not applicable on Linux.

| tool | category | schema summary (non-`session` fields; * = required) | wayland status | notes |
|---|---|---|---|---|
| click | input | pid, window_id, x, y, element_token, button∈{left*,right,middle}, count∈{1,2,3}, modifier[], scope∈{window*,desktop}, coordinate_frame, capture_id, from_zoom, delivery_mode∈{background*,foreground}, cursor_id, target | 🔸 pixel path OK on Wayland per schema; element_token path dead (no tokens issued); right/middle **error** on native Wayland (virtual-pointer is left-only); modifier clicks refused; bg delivery → libei/portal to compositor focus or `background_unavailable` | richest tool — prefers element_token, falls to window-local px; `count:3` = triple-click; reports `hit:`, `popup:`, `selected:`, `retargeted_to:`; `from_zoom` translates zoom coords |
| double_click | input | pid*, window_id, x, y, element_token, delivery_mode, coordinate_frame, from_zoom, cursor_id | 🔸 same Wayland constraints as click (left-button-only via virtual-pointer) | redundant with `click{count:2}` |
| right_click | input | pid*, window_id, x, y, element_token, modifier, delivery_mode, coordinate_frame, from_zoom, cursor_id | 🔸 **right button unsupported on native Wayland** — expect error | token path dead; px path errors per click's button contract |
| drag | input | from_x*, from_y*, to_x*, to_y*, pid, window_id, button, modifier, duration_ms(500), steps(20), scope, coordinate_frame, from_zoom, delivery_mode, cursor_id, target | 🔸 schema silent on Wayland button limits — likely left-only | window-local screenshot px; X11 path is virtual-master-pointer glide |
| scroll | input | direction*, pid, window_id, x, y, amount(3), by∈{line,…}, element_token, scope, coordinate_frame, delivery_mode, cursor_id, target | 🔸 X11 path is Button4/5; Wayland → libei/portal at compositor focus | targets "focused region" of pid; element_token scroll dead w/o tokens |
| type_text | input | text*, pid, window_id, x, y, element_token, scope, coordinate_frame, delivery_mode, target | 🔸 Wayland: libei/portal → compositor input focus (no per-window bg targeting) or `background_unavailable`; element_token path dead | X11 XSendEvent KeyPress/Release, no focus steal |
| press_key | input | key*, pid, window_id, x, y, modifiers, element_token, scope, coordinate_frame, delivery_mode, target | 🔸 same delivery_mode contract as type_text | single keypress |
| hotkey | input | keys*, pid, window_id, x, y, element_token, scope, delivery_mode, target | 🔸 WM chords (super+*, alt+tab…) refused `wm_chord_unavailable`; app chords OK via delivery path | key array e.g. ["ctrl","c"] |
| set_value | input | pid*, value*, window_id, element_token, delivery_mode | ❌ dead on Wayland — no element_tokens issued | AT-SPI SetValue action; 9 Wayland mentions in schema — token is the only addressing mode that makes sense and none exist |
| move_cursor | input (agent overlay) | x*, y*, scope∈{synthetic?,desktop}, cursor_id, target | ✅ verified: no-scope move is synthetic-overlay only, "user pointer unchanged" | **scope=desktop moves the REAL OS pointer** — wisp/cua.py already passes scope:"desktop"; the default (no scope) is the safe overlay move |
| mouse_button_down | input | pid*, window_id*, x*, y*, button, coordinate_frame, from_zoom, cursor_id | 🔸 X11-oriented ("background X11 delivery"); pair with mouse_drag/up | held-button state machine for custom drags |
| mouse_button_up | input | pid, window_id, x, y, coordinate_frame, from_zoom, cursor_id | 🔸 same | releases held button |
| mouse_drag | input | x*, y*, pid, window_id, duration_ms, steps, from_zoom, cursor_id | 🔸 | move while button held |
| parallel_mouse_drag | input | drags* (array; fn-curve paths supported) | 🔸 X11 MPX/XI2 virtual master pointers — Wayland path unknown, likely degraded | multi-pointer concurrent drags (e.g. drawing) |
| bring_to_front | input | pid*, window_id | 🔸 Wayland: foreign-toplevel adapter (wlroots advertised ✓) — should work; refuses where no compositor adapter | persistent activation; use `delivery_mode:"foreground"` per-action instead for ordinary focus needs |
| set_window_frame | input | pid*, window_id*, x*, y*, width*, height* | 🔸 desktop-coordinate move/resize + independent readback verify | tiling WM — Hyprland may re-tile on next layout event |
| invoke_menu | input | pid*, window_id*, path* | ⚠️ AT-SPI-dependent; trees exist but menu resolution needs window identity — Junction's tree is app-scoped | never falls back to pixels; fails closed |
| get_desktop_state | observation | max_image_dimension, screenshot_out_file | ✅ full PNG capture + windows[] + capture_id; scale_factor 2.0; agent-overlay cursor drawn INTO capture (`not_excluded`) | **the primary observe primitive**; scope:"desktop" coordinate source |
| get_window_state | observation | pid*, window_id, include_accessibility_tree, include_screenshot, query, max_elements(5000), max_depth, timeout_ms(1000→120000), max_image_dimension, screenshot_out_file | ⚠️ AT-SPI tree: works but `accessibility_window_identity_unproven` → no tokens/frames; screenshot: ✅ live mapped windows, ❌ `surface_identity_unproven` for unproven surfaces; tree-only mode is cheap | returns elements[] + tree_markdown + screenshot + window_bounds; query projects to matching rows+ancestors; partial tree on timeout (`truncated`, `elements_complete:false`) |
| get_accessibility_tree | observation | (none) | ⚠️ degraded: processes[] = 918, **windows:[]** (X11-only enumeration) | skip for window discovery — use list_windows |
| get_screen_size | observation | (none) | ✅ 1728x1080 logical @ scale 2.0 | matches eDP-1 3456x2160/2 |
| get_cursor_position | observation | (none) | ✅ but returns the **synthetic** agent cursor, per-session — not the user pointer | use `hyprctl cursorpos` for the real pointer |
| list_windows | observation | on_screen_only, pid | ✅ 9 windows incl. all workspaces + AT-SPI-registered windows absent from hyprctl; fields: pid, window_id (large int), app_name, title, x/y/w/h + bounds{}, is_on_screen, z_index:null | **no focus flag** (`is_on_screen` only) — wisp's `_focused_window` finds nothing |
| list_apps | observation | (none) | ⚠️ works but is a raw process list incl. kernel threads (systemd, kthreadd…) | launch_path field feeds launch_app |
| zoom | observation | window_id*, x1*, y1*, x2*, y2*, pid | ✅ on capturable windows (foot → 296x222 JPEG); ❌ `screenshot_context_missing` without a same-session snapshot | ≤500px wide, 20% pad; needs live snapshot in SAME session label |
| parse_visual_regions | observation | capture_id*, options{kinds,max_regions,min_confidence} | ❌ `not_installed` — needs optional cua-perception extension | capture_ids are also session-scoped |
| verify_state | observation | pid*, window_id*, expect*[1–8 predicates: window{exists,bounds±tol} / element{selector{role,label_contains},exists,enabled,selected,value_equals}], stable_samples, timeout_ms, include_screenshot | ✅ window.exists satisfied in 102ms on foot; unknown/target_missing on phantom Junction window | deterministic verify step; `unknown` never implies success |
| get_agent_cursor_state | observation | session* | ✅ theme/motion/position/visibility/phase of session cursor | session-keyed; shows overlay state not real pointer |
| start_session | session | session, capture_scope(deprecated), cursor_theme | ✅ created "r1probe" (active, effective_scope:"window", desktop_capture_authorized:false) | optional; ordinary actions auto-create named sessions |
| end_session | session | session | 🔸 state mutator — untested | idempotent cleanup (cursor/recording/config hooks) |
| get_session | session | session | ⚠️ returns `session_not_started` on implicit transport; needs a started session | lifecycle/cursor/recording/idle status |
| list_sessions | session | cursor, limit | ⚠️ `sessions:[]` — per-transport-lease view; named sessions not listed across CLI calls | near-useless from one-shot CLI |
| escalate_session | session | session*, reason*, detail | ➖ deprecated compat — per-action capture modality replaces it | no deescalate tool exists |
| get_session_state | session | session | ➖ deprecated alias for legacy capture policy → use get_session | |
| set_agent_cursor_enabled | session/cursor | session*, enabled* | 🔸 untested; overlay show/hide | overlay is compositor-drawn (layer-shell) on Wayland |
| set_agent_cursor_motion | session/cursor | session*, glide/spring/turn/idle timings | 🔸 untested | motion physics tuning |
| set_agent_cursor_theme | session/cursor | session*, theme_id*, reduced_motion | 🔸 untested; themes via `cursor-theme` CLI (cua.default installed, v2.0.0) | |
| start_recording | recording | output_dir*, include_accessibility_tree, record_video, state_timeout_ms | 🔸 untested — daemon-wide recording already owned by "r4s"; per-session writes turn dirs (before/after state.json + pngs + evidence.json) | |
| stop_recording | recording | (none) | 🔸 untested — would stop r4s's recording; DO NOT call while owned | |
| get_recording_state | recording | (none) | ✅ recording:true, owner:"r4s", output_dir:/tmp/cua-rec-sess, next_turn:2, video_active:true | |
| replay_trajectory | recording | dir*, delay_ms, stop_on_error | 🔸 replays recorded action.json calls; element_token actions fail across sessions (tokens are per-snapshot), pixel clicks/keys replay cleanly | recording a replay is deliberate (regression diff) |
| get_browser_state | browser | pid, window_id, target_id, tab_id, scope_ref, query, include_screenshot, snapshot_format, continuation | ⚠️ refuses `browser_consent_required` on consumer profiles until browser_prepare grant | read-only inspection surface for bound tabs |
| browser_prepare | browser | pid, window_id, profile, strategy∈{existing_profile,…}, allow_launch | 🔸 state mutator — grants DevTools binding; existing-profile needs launch grant (`--grant existing-profile` at serve time) | never modifies/copies user profile; isolated-profile launch is allow_launch-gated |
| browser_click | browser | target_id*, tab_id*, ref, x, y, delivery_mode, input_route | 🔸 consent-gated upstream | click by element ref or viewport coords in exactly-bound tab |
| browser_navigate | browser | target_id*, tab_id*, url* | 🔸 consent-gated | http/https/about only |
| browser_type | browser | target_id*, tab_id*, ref*, text*, mode, replace | 🔸 consent-gated | CDP Input domain typing |
| browser_pointer | browser | target_id*, tab_id*, session*, action*, x,y/to_x,to_y/delta/ref | 🔸 consent-gated | hover/right-click/dbl-click/scroll/drag |
| browser_dialog | browser | target_id*, tab_id*, action*, dialog_id, prompt_text | 🔸 consent-gated | inspect/resolve JS alert/confirm/prompt/beforeunload |
| browser_download | browser | session*, target_id*, tab_id*, ref*, destination_root* | 🔸 consent-gated | save into explicitly approved dir only |
| browser_set_input_files | browser | target_id*, tab_id*, ref*, files* | 🔸 consent-gated | absolute local files → `<input type=file>` via CDP |
| page | browser (legacy) | action*, css_selector, javascript, text, pid, window_id, cdp_port, target_url_contains, user_has_confirmed_enabling, bundle_id, attributes, selector | 🔸 read-only get_text/query_dom by default; mutations need `CUA_DRIVER_ENABLE_LEGACY_PAGE_MUTATIONS=1` at daemon start | prefer typed browser_* tools; covers Chrome/Brave/Edge/Safari/Electron/CDP/UIA/AT-SPI fallbacks |
| check_permissions | config | (none) | ✅ atspi:true, dbus session bus ✓, wayland:true, wayland_enabled:true, x11:true, xsend_event:true | Linux permission probe |
| health_report | config | include, skip | ✅ overall:"ok" — all Wayland wlroots globals advertised (foreign-toplevel, screencopy, ext-image-copy, ext-output-source, **virtual-pointer**, wl_shm); AT-SPI bus reachable | best single-call diagnostics |
| get_config | config | (none) | ✅ capture_mode:"ax", max_image_dimension:1568, experimental_pip:false | |
| set_config | config | key+value (preferred) or legacy fields; capture_mode, max_image_dimension, experimental_pip* | 🔸 mutator — untested; experimental_pip is a no-op stub on Linux (issue #1729) | persists to ~/.cua-driver/config.json |
| check_for_update | config | (none) | 🔸 read-only GitHub check; honors stable/nightly channel | |
| install_extension | config | name*, confirm | 🔸 preview without confirm (no mutation) → re-call confirm=true installs verified signed artifact | cua-perception is the missing piece for parse_visual_regions |
| install_ffmpeg | config | confirm | 🔸 needed only for start_recording's video path on Linux | |
| clipboard_read | utility | include_text(default false) | ✅ types listed (STRING/TEXT/UTF8_STRING/text/plain…); text:null unless include_text; privacy-flagged, redacted from telemetry | |
| clipboard_write | utility | text / image_path / file_path (exactly one) | 🔸 mutator — untested | absolute local paths only |
| launch_app | utility | launch_path, name, bundle_id(ignored on Linux), urls[], additional_arguments | 🔸 untested; precedence launch_path > name (.desktop/cmd/xdg-open) > urls | background launch |
| kill_app | utility | pid* | 🔸 kill -9; escalation after cooperative close fails | unsaved state lost |

## TOP-10 for the act loop (observe → aim → act → verify)

1. **get_desktop_state** — the observe primitive. Full-output PNG in the
   exact coordinate space `scope:"desktop"` actions consume, plus
   on-screen windows and a session-scoped capture_id. Flawless on Wayland.
2. **click** — the act primitive. Pixel rung only here (`{scope:"desktop",
   x,y}` or `{window_id,x,y}`); left-button-only, no modifiers on native
   Wayland. `count:2/3` covers double/triple; `hit:`/`popup:`/`selected:`
   feedback fields are gold for loop verification.
3. **type_text** — text entry. Expect `delivery_mode:"foreground"` (or an
   already-focused target) since background Wayland delivery lands at
   compositor focus or `background_unavailable`.
4. **get_window_state** — per-window tree + screenshot. Elements lack
   tokens/frames on Wayland but remain the best *textual* evidence
   (role/label/value/actions per element); screenshot+window_bounds give
   the aim frame. `include_accessibility_tree:false` = cheap preview.
5. **scroll** — direction/amount/by; same delivery caveats as type_text.
6. **zoom** — cheap re-observation of a window region post-action without
   a full re-capture (needs same-session snapshot context).
7. **verify_state** — the verify primitive. Deterministic
   window/element predicates with satisfied/unsatisfied/unknown — exactly
   what a post-action check needs; ~100ms.
8. **press_key** / **hotkey** — key input rung (tab/enter/escape,
   ctrl-c/v…). WM chords refused — use Hyprland dispatch for those.
9. **list_windows** — window/app discovery for targeting
   (pid+window_id+bounds), the join key for everything above.
10. **move_cursor** — the agent-cursor overlay: aim display without
    touching the user pointer (no-scope call); `scope:"desktop"` is the
    real-pointer move wisp already uses.

Runners-up: `set_window_frame` (window geometry ops), `clipboard_read/
write` (clipboard-mediated copy/paste — the reliable text-insertion
fallback), `bring_to_front` (persistent focus proxying), `health_report`
(loop startup self-test), `start_recording`+`replay_trajectory`
(trajectory capture/regression replays), `get_screen_size` (cheap sanity).

## Wire-up verdict — where each high-value tool belongs in wisp

| tool | wisp file | why |
|---|---|---|
| click, double_click, right_click, drag, scroll, move_cursor, press_key, hotkey, type_text, set_value | `wisp/cua.py` (+ `wisp/pointer.py` backend) | `cua.py` is the typed-wrapper home — add `desktop_state()`, `screen_size()`, `cursor_position()`, `zoom()`, `verify_state()`, `type_text()`, `press_key()`, `hotkey()`, `scroll()`, `right_click()`, `double_click()`, `drag()`, `clipboard_read/write()`, `launch_app()`, `set_window_frame()`, `start/end_session()`, `agent_cursor_state()`, `health_report()` next to the existing `click/move_cursor/list_windows/window_state`. All should accept a `session` param and pass it through — required for zoom/capture_id/token-cache continuity since each call is a fresh transport. |
| scroll, double/right click, drag for CuaBackend | `wisp/pointer.py` | `Backend` already has `scroll(dx,dy)` capability flag (only ydotool advertises it today — add `"scroll"` to `CuaBackend.capabilities` and a `scroll()` that calls `cua scroll`). Add button/drag plumbing: `Outcome`-returning `click` variants keyed on button. Two Wayland-specific notes for `pointer.py`: (a) `move_cursor` with `scope:"desktop"` moves the REAL user pointer on Wayland — the docstring's "without changing the user's pointer" claim only holds for the no-scope overlay call, so the current `Cua.move_cursor` (scope:desktop) is a real-pointer move, same as ydotool — decide which semantics `[pointer]` should have; (b) on `background_unavailable`/`surface_identity_unproven`/`wm_chord_unavailable` errors, surface the driver's suggested escalation (`delivery_mode:"foreground"`, desktop-scope capture) rather than flat `tool_failed`. |
| get_desktop_state, get_window_state screenshot, zoom, verify_state, clipboard_read, launch_app, health_report | `wisp/tools/system.py` | The system-tool surface the act loop calls: `screenshot()` could prefer `cua desktop_state` (screenshot_out_file straight into `shots/` — no grim dependency, includes window list, works with panel off? — needs lid-closed test) while keeping grim fallback; `type_text`/`key`/`scroll` can route through cua when `pointer.backend==cua` for one consistent injector; `verify_state` is the missing post-action check the loop needs; `launch_app` gives a guarded app-launch tool. |
| get_window_state elements, list_windows | `wisp/grounding.py` `_a11y()` (fix, not wire-up) | The a11y grounding path is **double-dead** on Wayland: `_focused_window` looks for `focused/active` flags that `list_windows` never emits (only `is_on_screen`), and elements in `accessibility_window_identity_unproven` mode carry no `frame`/`bounds` so `_rect()` yields None for all → a11y always falls through to pixel providers. Fixes: pick focus via `hyprctl activewindow` (hypr.py) or `is_on_screen`+workspace rather than list_windows flags; treat elements as *textual* evidence only (name→query ranking for which window/region to zoom+pixel-ground), not coordinate sources. |
| start/stop_recording, replay_trajectory | `wisp/trajectories.py` | Driver-native trajectory capture (before/after PNG+state per action) — far richer than wisp's own trace format for training data. Coordinate ownership: driver recordings are session-scoped; use a fixed wisp session label. |
| browser_prepare + browser_* / page | new `wisp/browser.py` or `tools/mcpclient.py` sibling | Entirely consent-gated; needs daemon `--grant existing-profile` at serve time (service file change — operator decision). BrowserOS MCP (:9200) already covers this surface for wisp today; cua browser_* is redundant unless BrowserOS goes away. Low priority. |
| get_accessibility_tree | skip | X11-only window list; empty on Wayland. `list_windows` supersedes it. |
| parse_visual_regions | defer | needs `install_extension cua-perception` (signed optional ext); revisit after install. |
| escalate_session, get_session_state, page, escalate paths | skip | deprecated compat surface. |

## Probe log (live calls made, all read-only / overlay-only)

| call | result |
|---|---|
| get_screen_size {} | ✅ 1728x1080 @ 2.0 |
| get_cursor_position {} | ✅ synthetic (836,527) — real ptr per hyprctl: (171,718) |
| list_windows {} / {on_screen_only:true} | ✅ 9 / 2 windows |
| get_accessibility_tree {} | ⚠️ 918 procs, windows:[] |
| get_desktop_state {max_image_dimension:1568} | ✅ PNG 1568x980 + 2 on-screen windows + capture_id |
| get_window_state foot(45058, wid …075328) tree-only | ⚠️ degraded x11_property_fallback_partial, 1 window elem, token s00000001:0 |
| get_window_state junction(357860) tree-only | ⚠️ degraded accessibility_window_identity_unproven, 7 elems, 0 tokens/frames |
| get_window_state chromium(7531) tree-only | ⚠️ same, 124 elems, 0 tokens |
| get_window_state spotifast(69035) | ⚠️ same, 130 elems (all actions:[click], role:"") |
| get_window_state 1password/hermes | ⚠️ x11_property_fallback_partial, 1 window elem each |
| get_window_state foot +screenshot ×3 | ✅ PNG 1378x833 every time |
| get_window_state chromium(7529, wid …105872) +shot | ✅ PNG 1260x911 |
| get_window_state junction +screenshot ×3 | ❌ surface_identity_unproven every time |
| zoom foot region (session r1probe) | ✅ JPEG 296x222 (20% pad) |
| zoom junction (no prior shot) | ❌ screenshot_context_missing |
| verify_state foot window.exists | ✅ satisfied, 102ms, 2 samples |
| verify_state junction element.exists | ⚠️ unknown/target_missing (window not in hyprctl) |
| move_cursor {x:400,y:300} no scope, r1probe | ✅ overlay only; user pointer unchanged (hyprctl-verified) |
| get_agent_cursor_state r1probe | ✅ position (400,300), theme cua.default v2.0.0 |
| start_session r1probe | ✅ active, effective_scope window |
| list_sessions | ⚠️ sessions:[] (per-lease view) |
| get_session {} | session_not_started (implicit) |
| get_recording_state | ⚠️ recording:true owner:"r4s" — left untouched |
| clipboard_read {} | ✅ 5 MIME types, text:null |
| get_browser_state chromium | ⚠️ refused browser_consent_required → browser_prepare |
| parse_visual_regions capture_id | ❌ not_installed (cua-perception ext) |
| check_permissions | ✅ all six flags true |
| health_report | ✅ overall ok; all wlroots globals incl. virtual-pointer |
| get_config | ✅ capture_mode:ax, max_image_dimension:1568 |
