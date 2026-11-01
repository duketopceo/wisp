#!/usr/bin/env python3
"""Turn the Blender renders into the committed exports (KTD4).

    assemble_wisp_flame.py RENDER_DIR EXPORT_DIR

RENDER_DIR holds frames/<state>/NNNN.png (256 px, RGBA) and still-512.png
from build_flame.py. EXPORT_DIR receives loops/<state>-{64,256}.webp
(animated, lossy with alpha) and stills/wisp-flame-{20,32,130,512}.png.
"""
import pathlib
import sys

from PIL import Image

STATES = ("idle", "listening", "thinking", "speaking")
FPS = 24


def loop(frames, size, path, quality):
    imgs = [Image.open(f).convert("RGBA") for f in frames]
    if size != imgs[0].width:
        imgs = [im.resize((size, size), Image.LANCZOS) for im in imgs]
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=round(1000 / FPS),
                 loop=0, lossless=False, quality=quality, alpha_quality=80, method=6)


def main(render, export):
    render, export = pathlib.Path(render), pathlib.Path(export)
    (export / "loops").mkdir(parents=True, exist_ok=True)
    (export / "stills").mkdir(parents=True, exist_ok=True)
    for state in STATES:
        frames = sorted((render / "frames" / state).glob("*.png"))
        if not frames:
            sys.exit(f"no frames for {state} in {render}")
        loop(frames, 256, export / "loops" / f"{state}-256.webp", 70)
        loop(frames, 64, export / "loops" / f"{state}-64.webp", 80)
    still = Image.open(render / "still-512.png").convert("RGBA")
    for size in (20, 32, 130, 512):
        im = still if size == 512 else still.resize((size, size), Image.LANCZOS)
        im.save(export / "stills" / f"wisp-flame-{size}.png", optimize=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
