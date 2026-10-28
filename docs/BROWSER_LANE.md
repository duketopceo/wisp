# Browser lane

Wisp can do browser work in your own Chromium, in a tab group beside your
tabs, where you can watch it and stop it. It is off by default.

## Turn it on

1. Load `browser-extension/` as an unpacked extension (`chrome://extensions`,
   Developer mode, Load unpacked). It asks for `tabs`, `tabGroups`,
   `scripting` and access to web pages, nothing else.
2. `wispd config set browser.lane extension`
3. Ask Wisp to pair the browser lane, or run a browser task. Wisp answers
   with a six-digit code. Open the extension's toolbar popup, enter the code
   and press Pair. The code works once and for five minutes; five wrong
   guesses burn it.

Until step 3 is done, every browser call fails with a setup message and does
nothing. After a browser restart the extension has to be paired again.

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

- **Pairing first.** No pairing, no action.
- **One snapshot epoch.** A ref is good only for the snapshot that issued it.
  An older ref is refused, both here and in the page.
- **No secrets.** Password, one-time-code and card fields (by type,
  `autocomplete` token, name, id, label or placeholder) are listed as
  `[never filled]` and never filled. The same rule runs in Wisp
  (`cua_safety.sensitive_field`) and in the page (`browser-extension/lib.js`);
  a test checks they agree.
- **Web pages only.** `file:`, `chrome:`, `javascript:` and `data:` URLs are
  refused.
- **Kill switch.** `[cua] kill_switch` and the kill file refuse the lane too.
- **Audit.** Each step is one line in the cua audit log; typed text is
  recorded as its length only.

## Stop

Press **Stop Wisp** in the extension's popup. The extension stops at once,
closes its tabs (not the ones you kept) and tells Wisp, which ends the call
in flight in under a second and refuses the rest of that turn. The next turn
starts clean.

## How it talks

Wisp serves a small HTTP socket on `127.0.0.1:47315` (`[browser] port`), only
while the lane is on. The extension polls it. Every request needs the
extension's `chrome-extension://` origin, a loopback `Host` header and, after
pairing, the session token, so a web page cannot reach it. Nothing leaves
your machine.
