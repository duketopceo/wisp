# Wisp browser lane (extension)

An original Manifest V3 extension. It does nothing until you pair it with a
one-time code from Wisp. See `docs/BROWSER_LANE.md` for setup, the rules it
keeps and how Stop works.

- `manifest.json`: permissions `tabs`, `tabGroups`, `scripting` and
  `<all_urls>` host access, nothing else (a test fails on any addition).
- `background.js`: pairing, the poll loop, the tab group, the steps.
- `lib.js`: pure helpers (the never-fill field rule, ref epochs, URL check);
  tested under node.
- `popup.html`, `popup.js`: Pair and Stop.
