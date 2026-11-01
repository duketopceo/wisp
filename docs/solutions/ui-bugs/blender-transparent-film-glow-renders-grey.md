---
module: assets/brand/wisp-flame
date: 2026-11-01
problem_type: ui_bug
component: tooling
severity: medium
symptoms:
  - "A glow around an emissive object renders as a dull grey or brown disc once the transparent PNG is composited over a dark background"
  - "The glow looks right in Blender's viewport but wrong in the exported frames, stills and WebP loops"
root_cause: wrong_api
resolution_type: code_fix
framework_version: "blender 5.2.3 (EEVEE)"
tags:
  - blender
  - eevee
  - film-transparent
  - emission
  - bloom
  - alpha
  - webp
retire_when: "Blender gives emission and emissive volumes alpha coverage in film-transparent renders; check the Blender release notes for transparent-film emission alpha before relying on in-render glow"
---

# Blender glow renders grey in a transparent-film render

## Problem

The Wisp flame (`assets/brand/wisp-flame`) is rendered headless in Blender with
`scene.render.film_transparent = True`, so the loops and stills carry alpha and
sit on any background. The soft glow around the heart was a render-only
emissive volume (a sphere with an Emission shader on the Volume output). In
the exported frames it came out as a muddy grey disc, not a cyan glow.

## Symptoms

- After compositing the RGBA frames on `#0b0c11`, the area around the heart
  was a desaturated grey/brown blob behind the translucent shell.
- Raising emission strength made it worse, not brighter-cyan.

## What didn't work

- **Blended or dithered glow surfaces** (an alpha-blended sphere instead of a
  volume): visible sorting edges against the blended shell, and grain from
  dithered transparency.
- **Brighter volume emission and colour ramps**: the colour is not the
  problem; the missing alpha is.
- **A feathered, partly transparent heart** to blend it into the glow: the
  heart nearly disappeared, because its alpha dropped while the glow still
  had none.

## Solution

Take the glow out of the render and add it in post, with alpha.
`scripts/brand/assemble_wisp_flame.py` has `bloom()` (defined at
`scripts/brand/assemble_wisp_flame.py:21`), applied to every frame and still
before encoding:

1. Luminance of the frame, weighted by its alpha; keep only the bright part.
2. Two Gaussian blurs (about 5% and 1.5% of the frame width), summed.
3. Tint the blurred mask with the guide cyan, and use the mask itself as the
   glow's alpha.
4. Composite the frame over the glow layer, then add the tint where the frame
   was transparent so the glow stays additive.

The render-only halo volume was deleted from `build_flame.py`; the shell
material carries the near-heart brightening on its surface instead (emission
plus higher alpha nearer the heart).

## Why this works

In a film-transparent render, alpha comes from surface coverage. An emissive
volume, like the halo this scene used, adds colour to the pixel but no coverage, so
the pixel's alpha stays near zero while its RGB is non-zero. Saved as straight
alpha and composited, that colour is mostly thrown away or comes out wrong,
which is the grey disc. A post bloom builds the glow and its alpha together,
so the composite matches what was intended on any background.

## Prevention

- In film-transparent renders meant for compositing, do not rely on emissive
  volumes or emission-only geometry for glows or halos. Add glow in post
  (Pillow, the compositor's Glare node with an alpha-aware setup, or the
  consumer's own bloom).
- Check renders composited on the real background (contact sheet), not in the
  Blender viewport.
- Related traps hit on the same asset (Blender 5.2.3):
  - The glTF exporter drops animated emission, so keyed glow belongs on a
    render-only material copy.
  - NLA strips built from Blender 5 slotted actions need
    `strip.action_slot = ad.action_slot` or they animate nothing.
  - The AgX view transform washes out brand colours; use `Standard` when the
    palette must match exactly.
- `tests/test_wisp_flame_asset.py` (`AssembleTest`) runs `bloom()` on a
  synthetic frame and asserts it adds alpha around the bright area while
  corners stay transparent.
