---
title: Wisp Chrome Extension - Plan
type: feat
date: 2026-11-02
execution: code
---

# Wisp Chrome Extension - Plan

## Summary

Wisp already has a browser lane: `browser-extension/`, a plain-JavaScript MV3 extension that polls a loopback HTTP socket, installed unpacked and paired with a six-digit code. This plan turns it into a store-grade extension. It moves the source to WXT and TypeScript, replaces the loopback socket with Chrome native messaging, adds a side panel that shows each step and a Stop control, and narrows permissions. It then publishes to the Chrome Web Store behind a manual gate.

The target is a browser lane that is easier to install than HeyClicky's, asks for less, shows more of what it does, and sends nothing to a Wisp server because none exists.

## Problem Frame

HeyClicky shipped a Chrome extension on 2026-10-23 and moved it to one-click Chrome Web Store install on 2026-10-30 (see HeyClicky Comparison). Wisp's lane has the safety design (pairing, snapshot epochs, never-fill fields, Stop) but not the product shape around it.

What is wrong today, from reading `browser-extension/` and `wisp/tools/browser.py` at master `898258e`:

- **Install is a developer ritual.** Developer mode, "Load unpacked", then `wispd config set browser.lane extension`, then a code. There is no store listing and no updates.
- **Pairing is lost on every browser restart.** The session token lives in a service-worker variable (`LANE.token` in `browser-extension/background.js`).
- **The transport is the weakest link.** The lane is an HTTP server on `127.0.0.1:47315`. Any local process can send `Origin: chrome-extension://...` and a loopback `Host`, so the origin gate keeps web pages out but not other local programs. After pairing the token protects it, but the pairing code travels over the same open port. Other local accounts on the machine can reach the port too, which `luke-security-and-secrets` says to avoid for private text.
- **The worker is held awake by a polling hack.** `poll()` calls `chrome.runtime.getPlatformInfo()` in a loop. Chrome documents native messaging and active debugger sessions as the supported keep-alives.
- **It takes the user's focus.** `open` creates tabs with `active: true`, and `screenshot` activates the tab to call `captureVisibleTab`. A watchable lane should not steal the tab the user is reading.
- **Nothing shows progress in the browser.** The popup has Pair and Stop only. The user cannot see the step list, the current page or what is blocked without looking at the desktop.
- **Permissions are fixed at install.** `<all_urls>` is required, so every user grants every site before the first task. Chrome Web Store review treats broad host permissions as a reason for a closer look.

Counterargument, stated first: the unpacked lane works and is shipped behind an off-by-default flag. A store listing adds a review dependency, a privacy policy to maintain and a permission warning that scares some users. The audience that wants a watchable browser lane on Omarchy is small today. This plan is worth doing only if the extension is the trust feature that closes the gap with HeyClicky's Chrome lane, and only if it ships after, and without delaying, the v1.0.0 release. Unit U1 is a spike so the biggest unknowns are measured before the rest is built.

## HeyClicky Comparison

Observed on 2026-11-02 from public pages. Nothing here comes from running or decompiling HeyClicky.

### What exists

| Item | Finding | Source |
|---|---|---|
| Chrome Web Store listing | Exists. "HeyClicky", category Workflow & Planning, 197 users, no ratings, version 0.6.4, updated 2026-11-01, size 130 KiB, English only, offered by Humansongs, Inc. | https://chromewebstore.google.com/detail/heyclicky/bphdnlcghkpiaoiplkhfofpfboddahce |
| Store timeline | 2026-10-23 extension introduced, installed by the app. 2026-10-30 "Chrome in one click" from the Web Store, also Edge, Brave, Arc, Vivaldi. | https://www.heyclicky.com/changelog |
| Privacy terms | Section 3.6 "HeyClicky for Chrome". | https://www.heyclicky.com/privacy-policy |
| Public source | None found. Searches found `farzaa/clicky` (MIT, the original macOS app, last updated before the extension) and `farzaa/clicky-releases` (update feed). Neither holds the extension. | https://github.com/farzaa/clicky |
| Own landing page | No dedicated extension page. `/chrome` and `/extension` on heyclicky.com return the home page. | https://www.heyclicky.com/ |

### Features (from the store listing and changelog)

- Background jobs work in the sites the user is signed into, started by voice or text.
- Tabs open in a blue tab group beside the user's tabs, named after the job. A soft glow around the working page and a cursor show where it clicks.
- Finished jobs close the tabs they only needed along the way. Borrowed tabs return where they were, and the job never closes the user's own tabs.
- A toolbar button lists each working job, what it is doing and its tabs. One click stops them. Chrome's own "is debugging this browser" bar also stops them.
- Jobs hand passwords, verification codes and card numbers back to the user to type.
- The changelog says tasks on the page the user is already viewing ask whether to use that tab or a separate window.
- Private (incognito) windows are not supported.

### Permissions (public manifest embedded in the store page)

`debugger`, `tabs`, `nativeMessaging`, `storage`, `alarms`, `tabGroups`, `downloads`. Minimum Chrome 120, a module service worker, a popup action, no content scripts, no side panel, and no `host_permissions` key. Its store privacy disclosure lists personally identifiable information, health, financial and payment information, personal communications, location, web history and website content.

### Data path (privacy policy 3.6)

The extension talks only to the HeyClicky desktop app through native messaging and has no server of its own. Page content read for a task goes through the company's backend proxy to its AI providers and can be kept in the task's conversation history. The extension itself stores a cursor setting and a random browser-profile identifier.

### Pricing

The extension is free. Its work is metered by the app plan: Free $0 (25 talk, 25 agent messages a month), Pro $20 a month or $16 billed yearly (150 agent messages), Max $100 a month or $80 billed yearly (1,000 agent messages). Source: https://toolfolio.com/articles/is-heyclicky-free-pricing-and-windows-version and https://hokai.io/hub/tools/heyclicky, both third-party and read 2026-11-02. A page-reading job costs agent messages.

### Does well

- One-click install and update from the store, across five Chromium browsers.
- Per-job tab groups with a visible cursor and glow, and clean tab hygiene.
- A stop path that works from three places.
- A small package (130 KiB) with a narrow story: it does nothing on its own.

### Does badly or leaves open

- Requires the `debugger` permission, so Chrome shows its debugging bar for as long as a job runs, and the store review has a "dangerous permission" signal to weigh.
- The store text says "Requires the HeyClicky app for Mac" while its privacy policy and download pages list Windows. The listing text is out of date or Mac-only.
- Closed source. A user cannot read what the extension does with pages.
- Page text and screenshots reach a vendor proxy and model vendors. The store disclosure lists seven categories of user data.
- No Linux app, so no Omarchy users at all.
- Agent work is quota-limited by plan.

### Where wisp can be better, and the proof each claim needs

| Claim | Evidence required before it is made public |
|---|---|
| Open source, readable build | Repo link in the listing and a reproducible build check (U9). |
| No account, no Wisp server, no metering | `docs/TRUST.md` regenerated with the browser entry and the same text in the privacy policy (U8). |
| No debugging bar in the default path | Manifest test that `debugger` is absent (U2). |
| Narrower grant on first install | Manifest test for the optional host permissions and a recorded install walkthrough (U7). |
| Never steals focus | E2E test that the user's active tab is unchanged across a task (U4). |
| Works on Linux and Omarchy | E2E run on Omarchy's browser (U1, U4). |

No comparison copy ships unless its row has passed. `luke-agent-rules` bans unverified claims.

## Requirements

**Install and connection**
- R1. A user installs the extension from the Chrome Web Store, or loads it unpacked for development, and it connects to a running `wispd` with no pairing code and no port.
- R2. The extension talks to Wisp only through a Chrome native messaging host that `wispd` installs. No HTTP listener remains once the migration lands.
- R3. Nothing runs until the user presses Connect in the extension UI. That consent persists across browser restarts and is revoked by a Disconnect control or by `wispd browser uninstall-host`.
- R4. The extension survives service-worker restarts: it reconnects to the host and resumes with no repairing.

**Visibility and control**
- R5. A side panel shows connection state, the current task, the ordered step log with the origin of each step, and what is blocked, with a recommended action for each error.
- R6. Stop ends the lane in under one second from the side panel, the toolbar, a keyboard shortcut and Wisp, closes the task's tabs (kept tabs stay) and refuses the rest of the turn.
- R7. Tasks run in a tab group beside the user's tabs without changing the user's active tab. The lane never touches incognito windows or the user's own tabs.
- R8. A small light marks the element about to be acted on, honors `prefers-reduced-motion`, and adds no glow effects.

**Safety**
- R9. Password, one-time-code and card fields are listed as never filled, by the same rule in Python, TypeScript and in-page, with one shared fixture list.
- R10. Refs are valid only for the snapshot that issued them, and only http and https pages open.
- R11. The manifest requests the narrowest set that works and a test pins the list. Host access beyond what the user granted is not available.
- R12. Typed text is audited by length only. Page text and screenshots go to the configured model provider only, as `docs/TRUST.md` states.

**Quality and release**
- R13. The extension builds with zero warnings under strict TypeScript, and passes unit, end-to-end and accessibility tests in CI.
- R14. A release workflow builds the extension zip reproducibly, runs a dry-run submit, and never publishes without Luke's explicit action.
- R15. The store listing, permission justifications, privacy policy and `docs/BROWSER_LANE.md` describe what the code does and nothing else.

## Scope Boundaries

In scope: Chromium-family browsers on Omarchy and desktop Linux first; the extension, the native host, the side panel, store submission.

Not in this plan:
- A `debugger` (CDP) mode. Considered and deferred; see KTD4 and U10.
- Firefox and Safari builds. WXT can target them. Firefox needs a source zip for review and a different background model, and Wisp has no Firefox users to serve yet.
- macOS and Windows native host installers. The transport design is portable. The installers wait until those apps need the lane (`docs/MACOS.md`, `docs/WINDOWS.md`).
- A hosted service, accounts, telemetry or analytics in the extension.
- Reading the user's browsing history or running in the background without a task.
- Changing the `browser` tool's step set in `wisp/tools/browser.py`. The batch contract stays.

## Key Technical Decisions

| ID | Decision | Rationale |
|---|---|---|
| KTD1 | Build with WXT, TypeScript strict. Do not use Plasmo. | WXT 0.21.5 is MIT and npm shows it modified 2026-10-26. Plasmo's latest release is 0.90.5 on 2025-05-17, and its tracker has an issue titled "Is it ready to continue maintenance?". WXT builds for the other stores and has `wxt zip` and `wxt submit`. |
| KTD2 | Keep the source in `browser-extension/` and convert it in place. | `docs/BROWSER_LANE.md`, `docs/RELEASING.md`, `scripts/release/build.py` and `scripts/release/verify.py` already name the directory. A rename adds churn for no benefit. |
| KTD3 | Native messaging replaces the loopback socket. A host launcher execs `wispd nmhost`, which relays framed JSON to a Unix socket under `$XDG_RUNTIME_DIR/wisp/` with mode 0600. | Chrome enforces `allowed_origins` for the extension, so no code or port is needed. Chrome starts the host and keeps the service worker alive while the port is open (Chrome 105+). The socket matches the daemon's existing `SO_PEERCRED` model in `docs/IPC_CONTRACT.md` and the "protected sockets" rule in `luke-security-and-secrets`. |
| KTD4 | Do not request `debugger` in v1. Keep `scripting` plus `tabs` and `tabGroups`. | `debugger` adds a warning ("Access the page debugger backend"), Chrome's debugging bar and a heavier review. It buys trusted input events and screenshots of background tabs. U1 measures how often `el.click()` fails on real pages. If the failure rate is high, U10 adds `debugger` as an optional permission. |
| KTD5 | No required host permissions. Request `<all_urls>` as an optional host permission, from a user gesture in the side panel, with per-site grants available. | Chrome's minimum-permission policy applies to optional permissions too, but the install warning shrinks. `permissions.request()` needs a user gesture, which the Connect and "Allow this site" buttons provide. U1 confirms the flow. Fallback: required `<all_urls>`, as today. |
| KTD6 | No static `content_scripts`, no `web_accessible_resources`, no `externally_connectable`. Inject functions on demand with `scripting.executeScript` in the isolated world. | Keeps pages unable to message the extension and keeps review small. This is the current behavior and the manifest test already enforces it. |
| KTD7 | The side panel is the primary UI. The popup remains as the fallback for browsers without `sidePanel`. | The panel stays open across tabs and can hold a live step log. `sidePanel` needs Chrome 114+, `sidePanel.open()` 116+. The current minimum is 116. |
| KTD8 | Side panel UI uses React from WXT's module, with plain CSS tokens. No Tailwind, shadcn or TanStack. | `luke-operator-ui` defaults to React on Radix and Tailwind. The panel has four views and a step list, so the extra layers cost bundle size (budget: 200 kb gzipped) and review surface. This overrides the default for stated reasons. |
| KTD9 | One field rule, one fixture file. `tests/fixtures/sensitive_fields.json` drives the Python test, the TypeScript unit test and the in-page E2E. | Today the rule is written three times (`wisp/cua_safety.py`, `browser-extension/lib.js`, and page functions in `background.js`) and a test compares two of them. A shared fixture makes drift fail CI. |
| KTD10 | The extension needs the `storage` permission for the consent flag and last known state. | Needed for R3 and R4. The current test forbids `storage`. U2 changes that test deliberately and lists the new allowlist. |
| KTD11 | A `commands` entry binds a global Stop shortcut. | R6 needs a keyboard path. The current test forbids `commands`. U2 updates it. |
| KTD12 | Delete the loopback HTTP transport after one release that ships both. | Two transports double the attack surface. `luke-agent-rules` prefers removing legacy once callers move. The native host works with an unpacked extension if its ID is pinned by a manifest `key`. |
| KTD13 | Wisp's own tab group keeps the name "Wisp". The light marker takes its color from Wisp's existing design tokens (`DESIGN-v2.md`) and is one small mark, no glow. | The brief says one small calm light on dark. HeyClicky's soft glow is the contrast to avoid. |

## High-Level Technical Design

Directional guidance, not implementation specification.

```
 Browser (Chromium family)                         Machine
 +-----------------------------+                   +--------------------------+
 | side panel (React)          |                   | wispd (Python daemon)    |
 |   state, step log, Stop     |                   |   tools/browser.py       |
 |        ^                    |                   |   LaneCore: queue,       |
 | background service worker   |   stdio, framed   |   epochs, audit, stop    |
 |   steps, tab group, epochs  | <---------------> |        ^                 |
 |   connectNative("com.wisp.  |   JSON via Chrome |        | unix socket 0600|
 |   browser")                 |                   |   nmhost relay           |
 |        |                    |                   +--------------------------+
 | scripting.executeScript     |                   ~/.config/<browser>/NativeMessagingHosts/
 |   (isolated world)          |                   com.wisp.browser.json  allowed_origins = [pinned ID]
 +-----------------------------+
```

Command flow, unchanged from today except the transport: `wispd` queues a batch, the relay hands it to the extension, the extension runs up to 20 steps, returns results and an optional proof PNG, and `wispd` writes audit lines.

Message sizes matter. Chrome limits a message from the host to the browser to 1 MB and from the browser to the host to 64 MiB. Commands are small. Proof screenshots travel browser to host, so they fit.

Host launcher: the `path` in the host manifest must be an absolute path on Linux and macOS, and Chrome passes the caller's origin as the first argument. A small launcher script in `~/.local/share/wisp/native-host/` execs `wispd nmhost "$@"`.

## Implementation Units

Each unit lands as its own PR on a branch named `feat/ext-<unit>-<slug>` (wisp's current prefix; `luke-delivery-workflow` lists `feature/`, see Open Questions). Tests ship in the same PR as the feature. No unit leaves a stub.

### U1. Spike: measured answers before the build

**Goal:** Decide KTD4, KTD5 and the focus model with evidence before building.
**Requirements:** R7, R11. **Dependencies:** none.
**Files:** `docs/research/2026-11-chrome-extension-spike.md` (new), `browser-extension/` (read only), throwaway fixtures under `tests/browser/`.

**Questions and method:**
1. Trusted input. Run the current lane's click and fill against a fixed list of 20 real pages (login-free): count how many reject synthetic clicks or ignore value-setter input. Record per site.
2. Optional host permissions. In a scratch extension, check that `permissions.request({ origins: ["<all_urls>"] })` called from a side-panel button works, persists across restart, and lets `executeScript` run in a tab the service worker created.
3. Focus model. Compare three ways of staying out of the user's way: `tabs.create({ active: false })` plus `captureVisibleTab`; an unfocused dedicated window; and the current behavior. Record whether proof screenshots still work for each.
4. Native host paths. Confirm the user-level manifest location and an `allowed_origins` match for Chromium, Chrome and Brave on Omarchy, and whether a custom `--user-data-dir` can carry its own `NativeMessagingHosts/` for hermetic tests. The Chrome docs list Chrome, Chrome for Testing and Chromium; Brave and Edge paths are to be confirmed, not assumed.

**Verification gate:** The research doc states a decision for each question with the raw counts. If the click-failure rate is above one in five pages, KTD4 reopens before U3 starts.

### U2. Scaffold WXT, port the lane 1:1, tighten the manifest tests

**Goal:** Same behavior and same transport, now TypeScript, built by WXT, with tests ported.
**Requirements:** R9, R10, R13. **Dependencies:** U1.
**Files:** `browser-extension/package.json`, `browser-extension/wxt.config.ts`, `browser-extension/tsconfig.json`, `browser-extension/entrypoints/background.ts`, `browser-extension/entrypoints/popup/` (HTML and TS), `browser-extension/src/lib/fieldrule.ts`, `browser-extension/src/lib/epoch.ts`, `browser-extension/src/lib/steps.ts`, `browser-extension/src/page/{snapshot,act,wait,scroll}.ts`, `browser-extension/tests/*.test.ts`, `tests/fixtures/sensitive_fields.json`, `tests/test_browser_lane.py`, `scripts/release/build.py`, `scripts/release/verify.py`, `.github/workflows/test.yml`.
**Approach:** Port function by function. The page functions (`pageSnapshot`, `pageAct`, `pageWait`, `pageScroll`) become modules that WXT bundles into the injected function. Verify each dependency name with `npm info` before install, pin exact versions, and review install scripts before running them. Add a CI job `extension` on Node 22 that runs typecheck, unit tests and `wxt build`. Update `scripts/release/build.py` and `verify.py` so the release tree carries the built unpacked folder, not only sources. Pin the dev extension ID with a manifest `key` so the host manifest can name it.
**Test files:** `browser-extension/tests/fieldrule.test.ts`, `browser-extension/tests/epoch.test.ts`, `browser-extension/tests/steps.test.ts`, `tests/test_browser_lane.py` (manifest and parity classes).
**Test scenarios:**
- Every case in `sensitive_fields.json` agrees across `wisp/cua_safety.py`, the TypeScript rule and the in-page rule.
- A ref from an older snapshot epoch is refused; a ref before any snapshot is refused.
- 21 steps are refused; `file:`, `chrome:`, `javascript:`, `data:` and `blob:` URLs are refused.
- The built manifest lists exactly `tabs`, `tabGroups`, `scripting` and `<all_urls>` at this stage, with no remote code and no `eval` or `new Function` in the bundle.
**Verification gate:** `npm run typecheck`, `npm test`, `npm run build` all clean with zero warnings; `python -m unittest tests.test_browser_lane` passes; an unpacked load of `.output/chrome-mv3` completes the existing end-to-end pairing against a local `wispd` test fixture.

### U3. Wisp side: shared core, Unix socket, `nmhost`, host install

**Goal:** `wispd` serves the lane over a protected socket and installs the native host.
**Requirements:** R1, R2, R3, R12. **Dependencies:** U1, U2.
**Files:** `wisp/tools/browser.py` (split transport from `LaneCore`), `wisp/tools/browser_nm.py` (new: framing, relay, host manifests), `wispd` (new subcommands `nmhost`, `browser install-host`, `browser uninstall-host`, `browser status`), `wisp/settings_schema.py`, `docs/CONFIG.md`, `tests/test_browser_lane.py`, `tests/test_browser_nm.py` (new).
**Approach:** Extract the queue, epoch, audit, stop and kill-switch logic from `Lane` into a transport-neutral core. The HTTP handler and the new socket handler both call it. `install-host` writes the launcher and one host manifest per detected browser, with owner-only modes from creation, and prints exactly what it wrote. `uninstall-host` removes only the files it recorded, by exact path, never by pattern. The socket path and the host name come from config and constants, not literals scattered in code.
**Test scenarios:**
- Framing: 32-bit native-order length prefix round-trips; a frame over 1 MB from host to browser is refused; a malformed or truncated frame closes the connection and logs a typed error.
- The socket is created 0600; a connection from another uid is refused.
- With the lane off, every call returns the existing setup message and does nothing.
- `install-host` is idempotent, writes only inside the browser config directories it names, and `uninstall-host` leaves unrelated files alone.
- The host manifest contains the pinned dev ID and, once known, the store ID, and no wildcards.
- Stop from the browser side ends an in-flight call in under one second and refuses the rest of the turn.
**Verification gate:** `python -m unittest discover -s tests` passes in CI; the new tests exercise the relay against a fake stdio peer; a manual run on Omarchy Chromium connects with `allowed_origins` set and refuses an unlisted extension.

### U4. Extension side: native transport and the consent flow

**Goal:** The extension connects through `connectNative`, survives worker restarts and drops the poll loop.
**Requirements:** R1, R3, R4, R7. **Dependencies:** U3.
**Files:** `browser-extension/src/lib/transport.ts`, `browser-extension/entrypoints/background.ts`, `browser-extension/src/lib/state.ts`, `browser-extension/wxt.config.ts` (permissions: add `nativeMessaging`, `storage`), `tests/test_browser_lane.py` (new allowlist), `browser-extension/tests/transport.test.ts`.
**Approach:** The worker opens the port only when the stored consent flag is set. On disconnect it reconnects with backoff, and restores task state from `storage.session`. `tabs.create` runs with the focus model chosen in U1. Remove `getPlatformInfo`. Keep the HTTP transport behind a build flag for exactly one release (KTD12) and delete it in U11.
**Test scenarios:**
- Killing the host mid-batch fails that batch with a clear error and the extension reconnects within the backoff window.
- Restarting the service worker mid-task does not lose the task's tab group or kept-tab set.
- With consent unset, the extension makes no native call.
- The user's active tab is the same before and after a task (focus test).
- Incognito windows are refused with a message that says why.
**Verification gate:** Playwright E2E loads the built extension in Chromium with a temp profile that carries its own native host manifest, runs the fixture task end to end, and asserts the focus invariant. `npm test`, `npm run build` and the Python suite pass.

### U5. Side panel, toolbar badge, Stop shortcut

**Goal:** The user sees and controls the lane from the browser.
**Requirements:** R5, R6. **Dependencies:** U4.
**Files:** `browser-extension/entrypoints/sidepanel/{index.html,main.tsx,App.tsx,styles.css}`, `browser-extension/src/ui/{StepLog,ConnectionCard,ErrorAction}.tsx`, `browser-extension/entrypoints/popup/` (fallback), `browser-extension/wxt.config.ts` (`sidePanel`, `commands`), `browser-extension/tests/ui/*.test.tsx`, `browser-extension/e2e/sidepanel.spec.ts`.
**Approach:** Apply `luke-operator-ui` where it fits a small surface. Open to the current task: the panel answers what changed, what to do next and what is blocked without a click. Four status colors only; blue only for links and the primary action. Every error names the cause and a button ("Wisp is not running. Start it, then [Retry]"). Empty state has the three parts: what appears here, why it is empty, what to do. Skeleton over spinner. Keyboard: `Esc` closes details, Stop is the first tab stop, and `commands` binds a Stop shortcut. The command palette and `j`/`k` list navigation are advisory for this surface and are not built (operator-ui allows this for overlays); the palette becomes a follow-up only if the panel grows past four views. Body text 13 to 14 px.
**Test scenarios:**
- Not connected, connected idle, running, stopped and host-missing states each render with the correct action.
- A step log of 20 steps renders with origins, truncated to about 140 characters, and does not exceed the layout.
- Stop from the panel, from the toolbar and from the shortcut each end the lane within one second in E2E.
- axe reports no violations; every control is reachable by Tab; focus is visible; `role="alert"` on errors; `prefers-reduced-motion` is honored.
- Throttled network and killed host both produce the error state, not a blank panel.
**Verification gate:** E2E suite and axe pass in CI. Screenshots of each state, light and dark, are attached to the PR. Bundle under 200 kb gzipped, measured and printed in CI.

### U6. Guiding-light page marker

**Goal:** A small light shows where the lane is about to act.
**Requirements:** R8. **Dependencies:** U4.
**Files:** `browser-extension/src/page/marker.ts`, `browser-extension/tests/marker.test.ts`, `browser-extension/e2e/marker.spec.ts`.
**Approach:** Inject on demand with the step, never as a content script. A closed shadow root holds one dot with `pointer-events: none`, high z-index and the Wisp accent. It moves to the element's rect, dims after the step and removes itself on task end or Stop. With `prefers-reduced-motion` it jumps instead of gliding. No blur, no glow, no pulsing loop.
**Test scenarios:**
- The marker never intercepts a click (a fixture button under it still fires).
- The marker is gone after `done`, after Stop and after navigation.
- A page style sheet that targets every element does not break or restyle it.
- Reduced motion sets duration to zero.
**Verification gate:** E2E passes; a screenshot shows the marker on a dark and a light page; the page's own DOM and layout are byte-identical outside the shadow host after removal.

### U7. Narrow the host permission

**Goal:** Install asks for less; the user grants sites from the panel.
**Requirements:** R11. **Dependencies:** U1 (decision), U5.
**Files:** `browser-extension/wxt.config.ts`, `browser-extension/src/lib/grants.ts`, `browser-extension/src/ui/SiteGrant.tsx`, `tests/test_browser_lane.py` (manifest allowlist), `browser-extension/tests/grants.test.ts`, `browser-extension/e2e/grants.spec.ts`.
**Approach:** Implement KTD5 if U1 confirmed it. The first task that needs a site shows "Allow Wisp on example.com" and "Allow on all sites" in the panel. A refused or revoked grant fails the step with the panel's error-and-action pattern. If U1 failed, record the reason in the research doc, keep required `<all_urls>` and skip this unit.
**Test scenarios:**
- Install-time manifest has no `host_permissions` and lists `<all_urls>` under `optional_host_permissions`.
- A step on an ungranted origin fails with the grant prompt and does nothing.
- A grant persists across a browser restart; a revoke takes effect on the next step.
**Verification gate:** Manifest test pins the final permission list: `tabs`, `tabGroups`, `scripting`, `nativeMessaging`, `storage`, `sidePanel`. E2E passes. No permission outside that list is present.

### U8. Docs, trust page and privacy policy

**Goal:** Every public statement matches the code.
**Requirements:** R12, R15. **Dependencies:** U3, U5, U7.
**Files:** `docs/BROWSER_LANE.md`, `docs/TRUST.md` (regenerated), `scripts/gen_trust.py`, `docs/PRIVACY.md`, `browser-extension/README.md`, `site/privacy-extension.html` (new; served at wisp.observer), `docs/INSTALL.md`, `CHANGELOG.md`, `tests/test_trust.py`, `tests/test_docs_lint.py`.
**Approach:** Rewrite `docs/BROWSER_LANE.md` for the native flow (install from the store, Connect, panel, Stop) and keep a short "load unpacked" developer section. Teach `scripts/gen_trust.py` about the browser lane: page text and screenshots go to the configured brain provider, nothing else leaves the machine. The privacy policy page must carry the Chrome Web Store Limited Use statement and state that the developer never reads user data, because the store requires a policy even for locally handled data. List each permission with its reason on the page and in the listing, and write nothing the code does not do.
**Verification gate:** `python3 scripts/gen_trust.py` leaves no diff; `tests/test_trust.py` and `tests/test_docs_lint.py` pass; every `wispd` command named in docs exists.

### U9. Release pipeline and reproducible build

**Goal:** One command builds the store zip; CI proves it matches the source; submission is a manual step.
**Requirements:** R14. **Dependencies:** U2, U7.
**Files:** `.github/workflows/extension-release.yml` (new, `workflow_dispatch` only), `browser-extension/package.json` (`zip`, `zip:firefox` scripts reserved, not enabled), `docs/RELEASING.md`, `scripts/release/build.py`.
**Approach:** The workflow runs `wxt zip`, rebuilds twice and compares hashes, then runs `wxt submit --dry-run`. A separate manual job without `--dry-run` exists but needs an approval environment. Credentials come from repository secrets named `CHROME_EXTENSION_ID`, `CHROME_CLIENT_ID`, `CHROME_CLIENT_SECRET` and `CHROME_REFRESH_TOKEN`; their values are never in the repo, logs or the PR. `.env.submit` is gitignored. Do not obfuscate; minification is allowed but the repo link is in the listing so reviewers can read the source.
**Test scenarios:**
- Two builds of one commit produce identical zips.
- The zip contains no source maps with absolute paths, no `.env` and no test files.
- The workflow fails when a required secret is missing and never prints one.
**Verification gate:** The dry run passes in Actions. The workflow cannot run on push or pull request, checked by reading its `on:` block. Luke triggers the real submission himself.

### U10. Deferred options, decided after measuring

**Goal:** Keep the follow-ups visible without building them.
**Dependencies:** U1 results, a month of real use.
- **Optional `debugger` mode** for trusted input and background-tab screenshots, only if U1 or field reports show a real failure rate. Check whether Chrome allows `debugger` as an optional permission before promising it.
- **Edge Add-ons listing.** WXT reuses the Chrome zip; the cost is a second account and review.
- **Firefox build.** Different background model and a source zip.
- **macOS and Windows hosts.** Windows needs a registry key per the Chrome docs.
- **Per-job tab groups** with the job name, as HeyClicky does, if more than one task runs at once.

### U11. Remove the loopback transport

**Goal:** One transport.
**Requirements:** R2. **Dependencies:** U8 shipped for one release, no open bug against the native path.
**Files:** `wisp/tools/browser.py`, `browser-extension/src/lib/transport.ts`, `browser-extension/wxt.config.ts`, `docs/CONFIG.md` (remove `[browser] port`), `wisp/settings_schema.py`, `tests/test_browser_lane.py`.
**Verification gate:** `rg 47315` returns nothing in source and docs; `rg "127.0.0.1" browser-extension/src` returns nothing; the full suite passes; a `wispd` that has no `[browser] port` key loads old configs without error.

## Security Model

Default deny. The extension has no way to act until the user connects it, and no way to reach beyond what the user granted.

| Threat | Control | Test |
|---|---|---|
| A web page talks to the extension | No content scripts, no `externally_connectable`, no `web_accessible_resources`. Injected code runs in the isolated world. The worker validates `sender` on every runtime message. | Manifest test; E2E with a hostile fixture page that posts messages |
| Another local program drives the lane | Chrome checks `allowed_origins` before starting the host. The relay talks to a 0600 Unix socket and refuses a different uid. No TCP port. | U3 socket-permission and uid tests |
| A page tries to get the lane to enter secrets | Password, one-time-code and card fields (by type, `autocomplete`, name, id, label, placeholder, aria-label) are listed as never filled, in Python, TypeScript and in-page. | Shared fixture, three-way parity test |
| Prompt injection from page text | Page text is returned as data and labeled untrusted by `wisp/tools/browser.py` before it reaches a brain. The `browser` tool stays confirm-tier (T2). Only http and https open. Each step is listed with its origin so a surprise hop is visible. | Fixture page whose text says "ignore your instructions"; assert no extra tool call |
| A stale ref hits the wrong element | One snapshot epoch per ref; an older ref is refused in Wisp and in the page. | Existing tests, ported |
| Data leaves the machine | No remote fetch, no analytics, no remote code, no `eval`. The only egress path is the configured brain provider, as for any Wisp turn. | Bundle grep test for URLs; `docs/TRUST.md` regeneration |
| The user cannot stop it | Stop from panel, toolbar button, shortcut and Wisp, each under one second. The kill switch and kill file refuse the lane. | U5 E2E, existing kill tests |
| Supply chain | Every dependency checked with `npm info` before install, exact pins, lockfile committed, install scripts read before running. No package is added to the page bundle that is not used. | CI `npm ci`; PR lists new dependencies |
| Secrets in the pipeline | Store API credentials only as repository secrets, referenced by name. Nothing is printed. | U9 workflow review |
| Incognito and private data | Incognito windows are refused. The extension is not enabled in incognito by default. | U4 E2E |

Security-critical code here is the field rule, the transport framing, the socket permission check, the epoch check and the host installer. Each is held to full line coverage, and `ce-code-review` runs with a security lens on U3, U4 and U7 before merge.

## Permissions

| Permission | Why | Added in |
|---|---|---|
| `tabs` | Read tab ids, status and URLs for tabs the lane created. | Today |
| `tabGroups` | Group and title the lane's tabs. | Today |
| `scripting` | Inject snapshot and act functions on demand. | Today |
| `nativeMessaging` | Talk to the Wisp host. Chrome shows "Communicate with cooperating native applications." | U4 |
| `storage` | Consent flag and last task state across worker restarts. | U4 |
| `sidePanel` | The live step view. | U5 |
| optional `<all_urls>` | Sites the user chooses to let Wisp work on. | U7 |

Not requested: `debugger`, `cookies`, `history`, `webRequest`, `downloads`, `activeTab`, `management`, `clipboardRead`, `alarms`. HeyClicky requests `debugger`, `downloads` and `alarms`; Wisp does not need them for the current step set.

## Publishing

Reference: https://developer.chrome.com/docs/webstore/publish and https://developer.chrome.com/docs/webstore/review-process.

1. Register a Chrome Web Store developer account. The fetched Chrome documentation says there is a one-time registration fee and does not state the amount. The developer email cannot be changed later, so use a dedicated address (Open Question 1).
2. Upload the zip from U9 as a new item. Fill the Store Listing, Privacy, Distribution and Test instructions tabs. The Privacy tab needs a single-purpose statement, a justification per permission, and the data-handling disclosures. Disclose handling even though the data stays local; the User Data FAQ says local handling still requires disclosure and a privacy policy.
3. Test instructions: a reviewer cannot install Wisp easily. Provide a short script and a screen recording of Connect, a task and Stop, and state that the extension does nothing until the Wisp app is running and the user presses Connect. This is the part most likely to cause a rejection or delay, so budget for one round of review feedback.
4. Prominent in-product disclosure: the Connect screen says in plain words that Wisp can read the pages and screenshots of tabs it opens, and asks for an explicit click, because the user-data policy requires disclosure inside the product and not only in the listing.
5. Review: the store reports most extensions complete in a few days and some take weeks. New developers, new extensions, `tabs` and broad host permissions each lengthen it. Submit with deferred publishing so approval does not publish by itself; the staged item expires after 30 days.
6. The new-publisher limit is two published extensions, which is enough.
7. Visibility: start unlisted or with trusted testers if the Distribution tab offers it, run Luke's trials against the store build, then go public. Public listing, the first submission, and each later submission are Luke's explicit actions.
8. After approval, add the store extension ID to the host manifest template (`allowed_origins`) in U3's installer and ship a `wispd` release that includes it.

Edge Add-ons reuse the same zip and are U10 work.

## System-Wide Impact

- `docs/IPC_CONTRACT.md` gains a note that the browser relay is not a `wispd.sock` client but its own socket, so the marked-peer and `SO_PEERCRED` rules there are unchanged.
- `scripts/release/verify.py` lists extension files by name; U2 updates it, and a release without the built folder must fail verification.
- `[browser] port` config disappears in U11; old configs must still load.
- The unit-test CI job gains an `extension` job on Node 22. The existing Python job is untouched.
- The extension adds a Node toolchain to a repo whose Node use today is the site build and the light-budget scripts. Keep it under `browser-extension/` with its own lockfile.

## Risks and Dependencies

| Risk | Impact | Mitigation |
|---|---|---|
| Store review rejects or stalls the extension | The release waits | Narrow permissions (U7), reviewer script and recording, unlisted track first, keep the unpacked path documented |
| Synthetic clicks fail on many real sites | The lane looks broken | U1 measures it; U10 optional `debugger` is the planned answer |
| Sandboxed browsers (Flatpak, Snap) cannot run the host | No connection for those users | Doctor check reports the browser package type and says so; document the supported installs |
| Native host path differs for Brave, Edge, Vivaldi | Missing connection | U1 confirms paths; `wispd browser status` lists what it found and what it did not |
| Extension ID changes between dev and store | Host refuses | Pinned dev `key`; installer writes both IDs; the store ID is added in the release after approval |
| Chrome changes MV3 service worker rules again | Reconnect bugs | Reconnect and state restore are tested by killing the worker; minimum Chrome version pinned and tested |
| WXT or a dependency is compromised | Supply-chain exposure | Exact pins, lockfile, `npm info` check, review install scripts; keep dependency count low |
| Public comparison copy overstates | Trust loss | The Comparison table's evidence column gates every claim |

## Documentation and Operational Notes

- Support path: `wispd browser status` prints whether the host manifest exists per browser, whether the socket is up, and whether the extension has connected. It is the first thing a user runs when Connect fails.
- The extension's version follows the Wisp release train; the store build and the repo tag name the same commit.
- The extension makes no network request of its own, so there is nothing to monitor. A broken host shows up as a `wispd doctor` line.

## Open Questions

For Luke. Each has a recommended default; the plan proceeds on the default unless he says otherwise.

1. **Timing.** Does this start before or after the v1.0.0 release? Recommendation: after the tag, so it does not compete with release trials. U1 can run earlier because it changes no product code.
2. **Store account and identity.** Which Google account and email owns the listing (it cannot be changed later), and is the publisher Luke personally or an entity? A publisher who declares as a trader has contact details shown on the listing; HeyClicky's listing shows a company address and phone. Registration is a one-time fee (the fetched docs do not state the amount).
3. **Submission authority.** The plan makes every store submission and the first public listing Luke's own action. Confirm, or name who may click Submit.
4. **Consent across restarts.** Should Connect persist across browser restarts (recommended, shown by a toolbar badge and cleared by Disconnect), or re-confirm each browser session as the current lane does with re-pairing?
5. **Browser scope for v1.** Which of Chromium, Brave and Chrome on Linux must work on day one, and which browser does Omarchy install by default? U1 and U3 test the answer.
6. **Host access.** Optional `<all_urls>` with per-site or all-sites grants from the panel (recommended, KTD5) or required `<all_urls>` at install as today (one fewer step, bigger install warning)?
7. **Trusted input.** Accept shipping without `debugger` in v1 (recommended, KTD4)? Without it, pages that ignore synthetic clicks and screenshots of background tabs are limited, and the lane may need to keep the task tab in front.
8. **Name and visibility.** Is "Wisp" the store name, and does Luke want an unlisted or trusted-tester stage before public (recommended)? The store listing must be checked for a name collision.
9. **Branch prefix.** This plan uses wisp's existing `feat/` prefix; `luke-delivery-workflow` lists `feature/`. Keep `feat/`?

In-plan items that block a unit: the U1 results decide KTD4, KTD5 and the focus model.

## Sources and Research

- Chrome extension docs index and Manifest V3: https://developer.chrome.com/docs/extensions
- Native messaging (host manifest, locations, protocol limits of 1 MB host to browser and 64 MiB browser to host, `allowed_origins`): https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging
- Service worker lifecycle (30 second idle, a native messaging port keeps the worker alive from Chrome 105, active debugger sessions from Chrome 118): https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle
- Side panel API (Chrome 114+, `open()` 116+): https://developer.chrome.com/docs/extensions/reference/api/sidePanel
- Permission list and warnings (`debugger`, `nativeMessaging`): https://developer.chrome.com/docs/extensions/reference/permissions-list
- `chrome.debugger` API: https://developer.chrome.com/docs/extensions/reference/api/debugger
- Web Store publishing, registration, review process, user data FAQ and minimum permission policy: https://developer.chrome.com/docs/webstore/publish, https://developer.chrome.com/docs/webstore/register, https://developer.chrome.com/docs/webstore/review-process, https://developer.chrome.com/docs/webstore/program-policies/user-data-faq
- Samples repo: https://github.com/GoogleChrome/chrome-extensions-samples (side panel, native messaging and tab-group samples to read before U4 and U5)
- WXT: https://wxt.dev, publishing guide https://wxt.dev/guide/essentials/publishing.html (`wxt zip`, `wxt submit`, `wxt submit --dry-run`)
- Plasmo: https://github.com/PlasmoHQ/plasmo (last release 0.90.5, 2025-05-17), maintenance question https://github.com/PlasmoHQ/plasmo/issues/1345
- HeyClicky: store listing, changelog and privacy policy URLs in the Comparison section
- Prior art in the repo: `browser-extension/`, `wisp/tools/browser.py`, `docs/BROWSER_LANE.md`, `tests/test_browser_lane.py`, `docs/plans/2026-10-27-feat-wisp-beat-competitors-plan.md` (B14 and KTD4), `docs/research/2026-10-25-clacky-teardown.md`

## Implementation Status (2026-11-02)

Built on `feat/chrome-extension`. The publisher account, store listing and any submission are deferred by decision.

| Unit | Status | Notes |
|------|--------|-------|
| U1 Spike | Partly | No research doc and no 20-page click-failure count (no network on the build box). Answered by building: a headless Chromium loads the unpacked extension and a custom `--user-data-dir` carries its own `NativeMessagingHosts/`; a background tab opened with `active: false` loads and is scriptable; `permissions.contains` on a port origin is covered by a port-less host permission. Found: `captureVisibleTab` needs the literal `<all_urls>` permission, so per-site grants cannot screenshot (see below). KTD4 stands: no `debugger`. |
| U2 Scaffold and port | Done | WXT 0.21.5, strict TypeScript, vitest; the shared `tests/fixtures/sensitive_fields.json` is read by Python and TypeScript. |
| U3 Wisp side | Done | `wisp/tools/browser_nm.py`, `wispd nmhost`, `wispd browser install-host / uninstall-host / status`; 0600 socket, uid check. The core was not split into a transport-neutral class: the `Lane` gained a native client beside the HTTP one. |
| U4 Native transport and consent | Done | Consent in `storage.local`; reconnect on browser start; step log and lane state survive a worker restart. |
| U5 Side panel, badge, Stop | Done, except | Panel, badge and `Alt+Shift+S` are done; axe passes in light and dark. No popup fallback. State screenshots are kept outside the repo. |
| U6 Page marker | Deferred | |
| U7 Optional host permission | Done | Manifest pinned by a snapshot and by Python allow and forbid lists. Deviation: a screenshot asks for all sites once (Chrome requires `<all_urls>` to capture a tab). |
| U8 Docs | Partly | `docs/BROWSER_LANE.md`, `docs/CONFIG.md`, `README.md`, `CHANGELOG.md`, extension README done. `docs/TRUST.md`, `gen_trust.py` and the privacy page are not touched. |
| U9 Release pipeline | Deferred | With the store submission. Release payload verification now lists the new extension sources. |
| U10 Deferred options | Deferred | |
| U11 Remove loopback transport | Deferred | By design, one release after this ships. |
