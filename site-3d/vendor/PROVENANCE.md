# Vendored website assets

- `../assets/wisp-flame/*`: published from `assets/brand/wisp-flame/export/`
  by `scripts/site/build_3d.py` (idle loop and stills); not stored here.
  The homepage itself is built from `site-app/` (see its `public/credits.txt`).
- `../wisp/gl.mjs`: the light's look follows ThreeUI Community `energy-orb`
  (https://github.com/MengTo/threeui, MIT, Copyright (c) 2026 Meng To) as a
  design reference; shader rewritten, with no ThreeUI code copied.
  The ghost-pill button style is adapted from its `lumen-cta`. License:
  `THREEUI-LICENSE.txt`. No ThreeUI Pro or remote catalog media is used.
- `../light/fonts/newsreader-*-latin.woff2`: Newsreader (roman and italic),
  instanced to opsz 24 and wght 300-400 and subset to basic Latin with
  fontTools. Upstream: https://github.com/google/fonts/tree/main/ofl/newsreader
  SIL Open Font License 1.1: `OFL-Newsreader.txt`.

All runtime assets are local. External repository anchors are navigation,
not runtime requests. No analytics, provider API, microphone access, desktop
bridge, service worker, or framework is included.
