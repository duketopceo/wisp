# cua-driver `browser_*` tool family — clicklab backend feasibility (R3)

Date: 2026-10-04 · cua-driver 0.33.1 (`~/.local/share/cua-driver/cua-driver`, user
service `cua-driver.service`, daemon on `~/.cache/cua-driver/cua-driver.sock`) ·
probed live against the running daemon, a driver-owned isolated Chromium, and a
private second daemon carrying `--grant existing-profile`.

CLI access pattern: `cua-driver describe <tool>` / `cua-driver call <tool>
'<json>' [--socket <path>]`. `call` proxies to the running daemon; no `--grant`
flag — daemon auth flags are serve-time only ("fixed for the daemon lifetime and
cannot be changed by a tool call").

## Tool inventory (all 10 described verbatim via `describe`)

| Tool | Purpose | Required args | Notes |
|---|---|---|---|
| `browser_prepare` | Prepare an **owned** DevTools endpoint | none (pid required unless `allow_launch`) | Two paths: (a) `allow_launch:true` + `profile.mode=isolated_new/isolated_named` → spawns driver-owned Chromium (root-owned distro `/usr/lib/chromium` qualifies); (b) `strategy.kind=existing_profile` + `pid` + `window_id` → attach to a running browser's profile, gated by permission mode |
| `get_browser_state` | Bind (mode 1: `pid`+`window_id` → `target_id`+`tab_id`s) or snapshot (mode 2) | pid+window_id **or** target_id+tab_id | `snapshot_format`: `dom_refs_v1` (default) or `semantic_v2`; `include_screenshot`, `query` (role/name/text filter), `scope_ref`, `continuation` |
| `browser_click` | Click by `ref` or `x`/`y` viewport CSS px | target_id, tab_id (+ref or x,y) | `input_route`: `trusted` (Input.dispatchMouseEvent) or `dom_event` (synthetic `el.click()`); `delivery_mode`: `background`\|`foreground` |
| `browser_type` | Type into editable ref | target_id, tab_id, ref, text | `mode`: `insert_text` (Input.insertText, default) or `keystrokes`; `replace:true` selects-all first. Ref mandatory — no x/y variant |
| `browser_navigate` | Navigate tab to http/https/about URL | target_id, tab_id, url | Invalidates all refs |
| `browser_pointer` | hover / right_click / double_click / scroll / drag | target_id, tab_id, session, action | ref or x/y; scroll takes delta_x/delta_y; drag takes destination_ref or to_x/to_y |
| `browser_dialog` | inspect/accept/dismiss JS dialogs | target_id, tab_id, action | Opaque `dialog_id` generation; Linux accept/dismiss needs `delivery_mode=foreground` |
| `browser_download` | Click-to-download into approved dir | session, target_id, tab_id, ref, destination_root | Never returns URL/filename/path |
| `browser_set_input_files` | Set files on `<input type=file>` ref | target_id, tab_id, ref, files[] | ≤32 regular files, no symlinks, via CDP |
| `page` | **Legacy** compat tool | action (+pid/window_id per action) | `get_text`, `query_dom` read-only by default (AT-SPI path — `query_dom` returned "No elements found" on a real button page); `execute_javascript`, `click_element`, `insert_text`, `type_keystrokes` are **mutations gated to unrestricted daemon mode** |

## Binding model — verified

**There is no "attach by CDP URL" parameter anywhere.** Binding is:

1. **Driver-owned launch** (`allow_launch`, no pid): spawns
   `/usr/lib/chromium` with `--remote-debugging-port=0` + profile under
   `~/.local/state/cua-driver/browser-profiles/isolated-<uuid>`. Verified live —
   `endpoint_ownership.method=spawned_by_driver`, then `get_browser_state`
   bind → `binding_quality:exact`, `endpoint_access_class:driver_owned`,
   `mutation_allowed:true`. No grant needed; works on the **current** daemon.
   `end_session` reaps browser + profile cleanly.
2. **Existing-profile attach** (`strategy.kind=existing_profile`, `pid` +
   `window_id` anchor): the driver proves the DevTools endpoint by `/proc` owner
   + `/json/version` (`endpoint_ownership.method=listening_socket_pid`). If no
   endpoint exists it may open the browser's own remote-debugging toggle page
   ("bounded exact-window setup"). Requires `--grant existing-profile` on the
   daemon command line in standard mode (or bounded manifest / unrestricted /
   embedding host). **Current systemd daemon has no grant** →
   `browser_prepare` and bind both refuse with `browser_consent_required`.
   Verified working on a private `serve --socket /tmp/r3-cua.sock --grant
   existing-profile`: attached to neo (pid 378975, window 187654298523056)
   with **zero side effects** — it detected the already-listening `:49337`.
   `endpoint_access_class:existing_profile_approved`.

"Exactly-bound" = target resolved from a **native window id** (via
`list_windows`) correlated exact-or-refuse to a CDP target; the daemon mints
opaque session-scoped `target_id`/`tab_id`s — never raw CDP ids. "Heuristic
bindings" (e.g. picking a browser by name) are refused throughout.

## Ref semantics — verified

- Refs are `p<snapshot_id>:<index>` minted per snapshot; **invalidated by
  navigation and by any newer snapshot of the tab** (confirmed: `p3:26` refused
  `browser_ref_stale` after a later query snapshot minted p3/p4).
- `dom_refs_v1`: flat list `{ref, node, label, frame}` — compact (2.5 KB for
  clicklab index.html: buttons `id=btn-*`, inputs `id=chk-*`, selects,
  textareas). **No geometry.**
- `semantic_v2`: 52 KB — `outline` (indented a11y tree), `refs[]` with
  `role`, `name`, `actions` (`click`,`pointer`,…), `states`, `value`,
  `visibility` (`in_viewport`/`near_viewport`/…); `content_refs` for
  read-only nodes; snapshot budget stats (`omitted.offscreen` etc.).
  **Still no coordinates/bounding boxes.** Coordinates enter only as click
  *inputs* (x/y) or as the resolved click point echoed in the response
  ("clicked (187, 534)").

## Linux input posture — verified

On this machine (Wayland/Chromium), the default `trusted` + `background`
click **refuses**: `browser_input_trust_unavailable` — "Chromium's trusted CDP
Input route activates its standalone browser window on Linux". Escape hatches:

- `delivery_mode:"foreground"` → trusted `Input.dispatchMouseEvent` delivered;
  window may activate. Verified: lab page counter went `events:1 → 2`.
- `input_route:"dom_event"` → synthetic `el.click()`, stays background.
  Verified delivered (`events:0 → 1`) but response marks it `unverifiable`;
  produces untrusted events (isTrusted=false) — not equivalent input for a
  pointer lab.
- `browser_type` via `insert_text` worked fine in background (no activation).

## Gap analysis vs clicklab `run.py`'s evaluate calls

`run.py` (`scripts/clicklab/run.py`) uses neo `evaluate` for: `check()` score
reads (`window.__score`), per-task `__score` resets + `location.reload()`,
`calibrate_dom_origin` (`__score.lastClick`), `--dom` rect probe
(`getBoundingClientRect`), and `tabs` list/new/close for `open_lab`.

| clicklab need | cua `browser_*` equivalent | Verdict |
|---|---|---|
| `Runtime.evaluate` (score read, reset, rect probe, reload) | **None.** Typed surface has no JS eval. Legacy `page.execute_javascript` exists but refused `unbounded_operation_requires_unrestricted` — needs daemon relaunch unrestricted (`--dangerously-bypass-approvals`) or `CUA_DRIVER_ENABLE_LEGACY_PAGE_MUTATIONS=1` env; systemd unit carries neither | **Hard gap** |
| Element rects (`getBoundingClientRect`) | Snapshots expose zero geometry | **Gap** — would need CDP `DOM.getBoxModel` or keep evaluate |
| Click at coords / on element | `browser_click` x/y or ref — verified working (trusted, foreground mode) | OK (window activation acceptable — lab already gets own workspace LAB_WS=97) |
| Type into field | `browser_type` ref + text — verified | OK |
| Scroll/hover/drag/right-click | `browser_pointer` | OK |
| Tab lifecycle (list/new/close) | **No tab tools.** Navigate existing tab only; new browser = `browser_prepare` isolated launch | Rework `open_lab` |
| Screenshot | `include_screenshot` → viewport PNG (verified 3408×1886, background capture) | OK |
| `window.__score` read | DOM-rendered bits only via `page get_text` (AT-SPI) or snapshot text | Score object is JS-state — needs eval channel |

## VERDICT: **No — not a viable drop-in clicklab backend.**

The typed `browser_*` family covers the *input* half well (verified end-to-end:
isolated launch → bind → navigate → snapshot → ref/coord click → type), but
clicklab's spine is `Runtime.evaluate` — score reads, resets, rect probes,
reload — and cua deliberately omits eval from the typed surface. The only
eval-ish escape (legacy `page.execute_javascript`) demands daemon-wide
unrestricted mode, a persistent systemd-unit change for one feature.

What it would take to use cua anyway:

- **Own-the-browser layout (works today, no daemon changes):** `browser_prepare
  allow_launch` → isolated Chromium; read its `DevToolsActivePort` file for the
  ephemeral CDP port → drive `Runtime.evaluate`/`DOM.getBoxModel` over raw
  WebSocket for scoring; use cua only for trusted input + snapshots. At that
  point the raw CDP socket alone does everything cua does (Input domain,
  Page.navigate, captureScreenshot) — cua adds consent ceremony and ref
  bookkeeping a lab doesn't need.
- **Attach to neo:** requires restarting `cua-driver.service` with
  `--grant existing-profile` (unit edit = persistent change + kills live agent
  sessions) or running a parallel private daemon (`serve --socket
  <path> --grant existing-profile`) — verified working. Even then, no eval.
- **Session lifecycle caveat:** browser targets/tabs/refs belong to the
  transport's lifecycle session; use a persistent MCP connection (UDS socket or
  `cua-driver mcp` stdio), not one-shot `call`s. Refs must be re-minted after
  every navigation/snapshot.

**Recommendation:** if clicklab needs a second transport beyond neo MCP,
plain CDP WebSocket (neo at `127.0.0.1:49337`, or a wisp-owned chromium on its
own `--remote-debugging-port`) is strictly more capable with zero new deps.
Keep cua-driver for what it's actually for here — desktop-level actuation
(`click`, `type_text`, `list_windows`, screenshots) — not as a page-DOM driver.

## Wire-up notes (if pursued)

- Daemon socket: `~/.cache/cua-driver/cua-driver.sock` (MCP over UDS);
  `cua-driver mcp` is a stdio→socket proxy for MCP clients.
- Bind anchors: `list_windows` → `pid` + `window_id` (neo: pid varies per
  launch, window title `browseros-neo`/`wisp *lab · N - Chromium`).
- Neo CDP: chromium `:49337` raw (`--remote-debugging-port=49337`, profile
  `~/.browserclaw/profile`), claw shim `:49338`, MCP `:9211`. Main browser:
  chromium `:9108`, shim `:9107`, server `:9200`.
- Grants for existing-profile attach are immutable per-daemon:
  `cua-driver serve --grant existing-profile` (repeatable flag) or
  `--permission-mode unrestricted --dangerously-bypass-approvals`;
  `cua-driver revoke --session <id>` is deny-only.
- Session label: pass a stable `"session":"<label>"` on every call or refs /
  targets won't resolve across transports.
- Update available: v0.33.3 (daemon printed notice during private-serve test).
