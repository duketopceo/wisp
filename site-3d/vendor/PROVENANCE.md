# Vendored website assets

- `three.module.js`: Three.js **0.170.0**, unmodified minified ES module from
  `three@0.170.0`, `package/build/three.module.min.js`.
  Package: https://registry.npmjs.org/three/-/three-0.170.0.tgz
  MIT license: `THREE-LICENSE.txt`.
- `../assets/outfit-variable.ttf`: unmodified Outfit variable font.
  Upstream: https://github.com/google/fonts/tree/main/ofl/outfit
  File: https://raw.githubusercontent.com/google/fonts/main/ofl/outfit/Outfit%5Bwght%5D.ttf
  SIL Open Font License 1.1: `OFL-Outfit.txt`.
- `../assets/companion.png`: repository `assets/readme/companion.png`.
  An actual companion component sheet, not a live-run recording.
- `../assets/mark.svg`: repository `assets/icons/src/bar-listening.svg`,
  copied unchanged. No new brand mark.
- `../light/light.mjs`: the light's fragment shader is adapted from ThreeUI
  Community `energy-orb` (https://github.com/MengTo/threeui, MIT, Copyright
  (c) 2026 Meng To): recoloured to the wisp `guide` token, smaller and slower.
  The ghost-pill button style is adapted from its `lumen-cta`. License:
  `THREEUI-LICENSE.txt`. No ThreeUI Pro or remote catalog media is used.
- `../light/fonts/newsreader-*-latin.woff2`: Newsreader (roman and italic),
  instanced to opsz 24 and wght 300-400 and subset to basic Latin with
  fontTools. Upstream: https://github.com/google/fonts/tree/main/ofl/newsreader
  SIL Open Font License 1.1: `OFL-Newsreader.txt`.

All runtime assets are local. External repository anchors are navigation,
not runtime requests. No analytics, provider API, microphone access, desktop
bridge, service worker, or framework is included.
