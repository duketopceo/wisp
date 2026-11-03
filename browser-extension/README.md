# Wisp browser lane (extension)

A Manifest V3 extension, built with WXT and strict TypeScript. It does
nothing until you press Connect in its side panel, and it holds no site
permission until you grant one. `docs/BROWSER_LANE.md` has setup, the rules
it keeps and how Stop works.

```sh
npm ci
npm run build           # .output/chrome-mv3/, load it unpacked
wispd browser install-host --dev
```

- `wxt.config.ts`: the manifest. Permissions are `tabs`, `tabGroups`,
  `scripting`, `storage`, `sidePanel` and `nativeMessaging`; every site is an
  optional host permission. The pinned `key` gives the unpacked build a stable
  id (the public half only).
- `entrypoints/background.ts`: wires chrome.* to the controller.
- `entrypoints/sidepanel/`: the panel (status, Stop, step log).
- `src/protocol.ts`, `src/native.ts`: the messages and the native messaging
  link, with consent and back-off.
- `src/lane.ts`: the tab group, the steps and the per-site grants.
- `src/controller.ts`: consent, Stop and the state the panel draws.
- `src/fieldrule.ts`, `src/page/*`: the never-fill rule and the functions
  injected into pages.
- `tests/`: unit tests (`npm test`). `scripts/`: checks on the built
  extension (`npm run check:build`). `e2e/`: headless Chromium against the
  real wispd lane (`npm run e2e`).
