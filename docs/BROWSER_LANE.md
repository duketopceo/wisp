# Browser lane

Wisp can do browser work in your own Chromium, in a tab group beside your
tabs, where you can watch it and stop it. It is off by default.

## Turn it on

You need Node 22 or newer once, to build the extension. A store listing is
not published yet.

1. Build it: `cd browser-extension && npm ci && npm run build`.
2. Load `browser-extension/.output/chrome-mv3/` as an unpacked extension
   (`chrome://extensions`, Developer mode, Load unpacked). It asks for
   `tabs`, `tabGroups`, `scripting`, `storage`, `sidePanel` and
   `nativeMessaging`, nothing else. It asks for no site up front.
3. Let the browser find Wisp: `wispd browser install-host --dev`. This writes
   a small launcher and one host manifest per browser you have
   (Chrome and Chromium, Brave and Edge). `--dev` allows the unpacked build's
   pinned id; for a build with another id use `--extension-id <id>`.
   `wispd browser status` shows what is installed and whether wispd is
   listening; `wispd browser uninstall-host` removes exactly those files.
4. `wispd config set browser.lane extension`
5. Click the Wisp icon to open the side panel and press **Connect Wisp**.

The panel remembers that you connected, across browser restarts. **Disconnect
Wisp** forgets it. Until you connect, every browser call fails with a setup
message and does nothing.

### Which sites

The extension holds no site permission when you install it. The first time
Wisp needs a site, the panel says "Wisp is waiting for your OK on
example.com" with an **Allow** button; Chrome then asks you. Nothing opens
or is read on that site until you allow it, and Stop ends the wait. A
screenshot needs more: Chrome only lets an extension capture a tab if it may
use every site, so the first screenshot asks for "all sites" once. Wisp still
asks before it opens each new site.

## What it does

One `browser` tool call is a batch of up to 20 steps:

| step | what it does |
|------|--------------|
| `open` | open an http or https page in this task's tab group (named "Wisp") |
| `snapshot` | list the visible links, buttons and fields with refs like `3:7` and the page text |
| `click`, `fill` | act on a ref from the latest snapshot |
| `scroll`, `wait_for` | scroll; wait for text or a selector (at most 15 s) |
| `screenshot` | proof screenshot saved under `~/.local/share/wisp/browser/output/` |
| `keep` | take a tab out of the group so it stays when the task ends |
| `done` | close the task's tabs (kept tabs stay) |

A new turn closes the previous turn's tab group. The tool is confirm-tier
(T2): it asks once per session like `mcp_call` does.

## Rules it keeps

- **Consent first.** Until you press Connect, nothing connects and no action
  happens. The extension has no `debugger` permission, no cookies, no history
  and does not run in private windows.
- **One snapshot epoch.** A ref is good only for the snapshot that issued it.
  An older ref is refused, both here and in the page.
- **No secrets.** Password, one-time-code and card fields (by type,
  `autocomplete` token, name, id, label or placeholder) are listed as
  `[never filled]` and never filled. The same rule runs in Wisp
  (`cua_safety.sensitive_field`) and in the page
  (`browser-extension/src/fieldrule.ts`); both tests read
  `tests/fixtures/sensitive_fields.json`, so they cannot drift.
- **Web pages only.** `file:`, `chrome:`, `javascript:` and `data:` URLs are
  refused.
- **Kill switch.** `[cua] kill_switch` and the kill file refuse the lane too.
- **Audit.** Each step is one line in the cua audit log; typed text is
  recorded as its length only.

## Stop

Press **Stop Wisp** in the side panel (or `Alt+Shift+S`). The extension stops at once,
closes its tabs (not the ones you kept) and tells Wisp, which ends the call
in flight in under a second and refuses the rest of that turn. The next turn
starts clean.

## How it talks

Chrome starts a small relay (wispd in its `nmhost` mode) when the extension connects, and
the relay passes length-prefixed JSON between Chrome and a Unix socket,
`$XDG_RUNTIME_DIR/wisp/browser.sock`. The socket is mode 0600 in a 0700
directory, and wispd refuses any peer that is not your user. Chrome only lets
the extension ids named in the host manifest start the relay. The messages are
`hello`, `cmd`, `result`, `stop`, `ping` and `bye`, defined in
`browser-extension/src/protocol.ts` and `wisp/tools/browser_nm.py`; each end
drops what does not fit. Nothing leaves your machine.

Wisp still serves the older loopback HTTP transport on `127.0.0.1:47315`
(`[browser] port`) for one more release, so an earlier unpacked extension
keeps working. It pairs with a six-digit code in its popup, as before.

## Known limits

- Opening a page in the background does not move your focus. A screenshot
  briefly shows Wisp's tab and then puts yours back, so the tab strip can
  flicker.
- If Wisp is not running, the extension retries five times over about
  fifteen seconds, then says so in the panel and waits for **Try again**.
- The Brave and Edge host manifest paths are not in Chrome's documentation;
  `install-host` marks them as such. Chrome and Chromium paths are.

## Developing

`cd browser-extension`, then `npm run typecheck`, `npm test`, `npm run build`,
`npm run check:build` (the built manifest against `tests/manifest.snapshot.json`)
and `npm run e2e` (headless Chromium, the real native host and a real wispd
lane, on local fixture pages; needs `npx playwright install chromium` once).
The manifest is pinned twice, by that snapshot and by an allow and a forbid
list in `tests/test_browser_nm.py`, so adding a permission takes two reviewed
edits.
