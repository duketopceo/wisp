# Wisp light (the /light/ preview)

## Direction

One small live light that guides a visitor down the page: a shaded core, a soft
wispy tail that trails motion and collapses at rest, and a slow breathing glow.
Wisp `guide` token on near-black, self-hosted Newsreader. The page keeps the
design, copy and credits PR #274 shipped; this work replaces its renderer. The
homepage, `/plain/`, `install.py` and the rc.2 pins are untouched.

## Choreography

The light rests beside each of the seven marks (hero, stops 01 to 05, install
block) and drifts between them as the page scrolls. It trails only while it
moves. At rest it draws nothing: the loop sleeps, and only the CSS breathing
runs (compositor, no script).

## Tokens

`--guide #7dcfff` core and glow, mid `#295f85`, canvas `#0b0c11`. The CSS orb
uses the same palette and the same size as the GL core; its gradient reaches
zero before its edge, as the GL glow does.

## Budgets (design targets; the gates in `tests/browser/light-budget.json` are the proof)

| Item | Moving | Resting |
| --- | --- | --- |
| rAF callbacks | display rate (transform every frame) | 0 |
| GL draws | at most 31 a second at any rAF rate, 1 call each | 0 |
| Geometry | 17 quads (core + 16 tail), one static buffer | none |
| Fragment work | analytic sphere, 2 noise taps on core pixels, no loops | none |
| Canvas | 400 CSS px box (240 under 760 px), pixel ratio at most 1.5, scale tiers 1 / 0.75 / 0.5 | unchanged |
| Layout reads | none in the loop; `scrollY` only | none |

Gates (see the test file for the exact numbers): draw rate and p95 draw interval
at 1x, 4x and 6x CPU throttle and a synthetic 120 Hz rAF; zero blank frames;
premultiplied invariant and transparent border pixels in every sampled frame;
no overshoot after the scripted scroll ends; non-increasing glow outward on rest
frames; zero animation frames, draws and transform changes over 2 s at rest;
monotone resolution step-downs with at most one CSS hand-off.

## Fallback

A CSS orb replaces the canvas for: no WebGL, a software or major-performance-caveat
renderer, context loss, a sustained runtime frame-budget breach on the lowest tier,
a draw error, a module load failure and reduced motion. Without reduced motion the
orb drifts with a CSS transition on `transform`. With reduced motion it snaps and
is re-placed only when the active stop changes. Without scripts it sits at the
hero mark.

## Evidence boundary

CI proves structure and cost ceilings under SwiftShader. It does not prove a
real Intel i3-class iGPU holds 30 fps; that stays a manual check on real hardware.
Claims on the page are limited to what `README.md` and `ROADMAP.md` support.

## Reuse

- `site-3d/wisp/sim.mjs`: `createSim({x, y, omega, tailN, maxRadius, ...})` returns
  `setTarget(x, y)`, `step(dt)`, `state` (`x y vx vy speed tailLen settled trail`),
  `trail` (unit-box offsets, `tailN * 2` floats), `trailAge` and `settled`. No DOM or GL.
- `site-3d/wisp/gl.mjs`: `createGlView(canvas, {onLost})` returns `null` when WebGL is
  unavailable or refused, else `{draw(state, time), resize(cssSize, dpr, scale), dispose()}`.
  `VERTEX_SRC` and `FRAGMENT_SRC` are exported strings. A three.js adapter would feed
  them to a `ShaderMaterial` and the sim's `trail` and `tailLen` as uniforms (`uTrail`,
  `uTailLen`, `uTime`, `uNoise`) on a 17-quad geometry (`aCorner`, `aSlot`).
- `site-3d/light/light.mjs`: page wiring only (marks, geometry cache, loop, fallback).
