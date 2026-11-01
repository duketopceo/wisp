# Wisp flame

Wisp's 3D mark: a translucent flame with a bright heart, in the guide-light
colors (`#7dcfff` core, `#295f85` mid, on `#0b0c11`). It has an idle loop and
three states. Plan: `docs/plans/2026-11-01-0123-feat-wisp-flame-asset-plan.md`.

Nothing uses it yet; the lock screen, overlay, bar and site adopt it later.

## Files

| Path | What it is |
|---|---|
| `source/build_flame.py` | The **source of truth**: a Blender script that builds the scene from nothing, exports the glTF and renders everything. |
| `source/wisp-flame.blend` | The scene as the script leaves it, with the render materials. Open it in Blender to look around. |
| `export/wisp-flame.glb` | Live 3D (three.js, Qt Quick 3D). Four animations: `idle`, `listening`, `thinking`, `speaking`. |
| `export/loops/<state>-{64,256}.webp` | Animated WebP with transparency, 48 frames at 24 fps, looping. 64 px for the bar and cursor at 2x, 256 px for the lock orb at 2x. |
| `export/stills/wisp-flame-{20,32,130,512}.png` | Idle stills. |
| `preview/index.html` | Local three.js viewer with state buttons. Not shipped. |
| `preview/qt-check.qml` | Qt Quick 3D load check. Not shipped. |

## The states

- **idle**: the tip sways like a candle, the heart breathes, the wisp trails.
- **listening**: taller and upright, a larger and brighter heart.
- **thinking**: a faster flicker in the heart; the wisp swirls.
- **speaking**: the heart pulses in syllable-like beats; the flame swells slightly with it.

In the glTF the states differ only by transforms and the tip-bend morph
weight; glTF players do not animate material values. The brighter heart and
the speaking glow, plus the Fresnel rim and the soft glow around the heart,
exist only in the rendered loops and stills. Use the loops where the exact
look matters.

## Rebuild

Blender has no Linux ARM64 build, so the scene is built and rendered on a Mac
with Blender (default `luke-pro-max1`, Homebrew cask) over SSH:

    scripts/brand/render_wisp_flame.sh [--host HOST] [--frames N]

That copies `build_flame.py` to the host, runs Blender headless, copies the
outputs back, and `scripts/brand/assemble_wisp_flame.py` writes the WebP loops
and PNG stills. Edit the script, not the `.blend`: a hand edit to the `.blend`
is overwritten on the next rebuild. If you do want to edit in Blender, make
the `.blend` the source of truth and stop using the script.

## Checks

- `tests/test_wisp_flame_asset.py`: glTF structure, loops, stills, size budgets.
- three.js: serve the repository root (`python3 -m http.server -d .`) and open
  `/assets/brand/wisp-flame/preview/` in a browser with WebGL.
- Qt Quick 3D: needs the `assimp` package (optional dependency of
  `qt6-quick3d`). In the desktop session:
  `QT_FORCE_STDERR_LOGGING=1 qml6 assets/brand/wisp-flame/preview/qt-check.qml`
  prints `wisp-flame: qt Success`.

## Provenance

Built for Wisp; no third-party models or textures. The preview's vendored
three.js loader is listed in `preview/vendor/PROVENANCE.md`.
