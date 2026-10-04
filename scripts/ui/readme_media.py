#!/usr/bin/env python3
"""Compose the README images from the real snapshot goldens (W33).

Every tile is a PNG that `scripts/ui/snap.py` rendered from the shipped QML
components through the real state reducer, on the dark theme. Nothing here
is drawn or generated: the script pastes goldens unscaled onto a labelled
sheet.

    python scripts/ui/readme_media.py            write assets/readme/*.png
    python scripts/ui/readme_media.py --check    exit 1 if the files differ

Output is deterministic for a given set of goldens (bundled Liberation Mono,
fixed layout, palette quantisation, oxipng when installed). Re-run after
`snap.py update` and commit the result.
"""
import argparse
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "qml" / "snapshots" / "dark"
OUT = ROOT / "assets" / "readme"
BG = (30, 28, 26)
FG = (200, 196, 190)
GAP, PAD, LABEL_H = 16, 20, 18

# name -> (title, rows); a row is a list of (scale, golden id, caption)
SHEETS = {
    "companion": ("Companion: orb states, listening pill, confirm card, "
                  "act console", [
        [("2x", "Creature__idle", "idle"),
         ("2x", "Creature__listening", "listening"),
         ("2x", "Creature__thinking", "thinking"),
         ("2x", "Creature__acting", "acting"),
         ("2x", "Creature__speaking", "speaking"),
         ("2x", "Creature__error", "error")],
        [("1x", "Pill__listening", "listening pill"),
         ("1x", "Bubble__confirm", "confirm card (W25)")],
        [("1x", "Console__acting", "act console, Esc stops (W24)"),
         ("1x", "Answer__done", "answer with good / wrong")],
    ]),
    "panel": ("Panel: Now, Agents, Memory and Settings tabs", [
        [("1x", "NowTab__acting", "Now"),
         ("1x", "AgentsTab__tasks", "Agents"),
         ("1x", "MemoryTab__filled", "Memory")],
        [("1x", "SettingsTab__ok", "Settings")],
    ]),
    "bar-mark": ("Bar mark: one glyph per state", [
        [("2x", f"BarMark__{s}", s) for s in
         ("idle", "listening", "transcribing", "deciding", "acting")],
        [("2x", f"BarMark__{s}", s) for s in
         ("speaking", "confirm", "awaiting_choice", "error", "offline")],
        [("2x", f"BarMark__{s}", s) for s in
         ("blocked", "stale", "suggestion", "done", "long_answer")],
    ]),
    "first-run": ("First-run card (wispd onboard)", [
        [("1x", "FirstRunCard__fresh", "fresh"),
         ("1x", "FirstRunCard__partial", "partial"),
         ("1x", "FirstRunCard__problem", "a step failed"),
         ("1x", "FirstRunCard__all_done", "done")],
    ]),
    "manage": ("Management app: Health, Spend, Audit, Binds", [
        [("1x", "HealthView__all_ok", "Health"),
         ("1x", "SpendView__ok", "Spend")],
        [("1x", "AuditView__rows", "Audit"),
         ("1x", "BindsView__global", "Binds")],
    ]),
}


def _pil():
    from PIL import Image, ImageDraw, ImageFont
    return Image, ImageDraw, ImageFont


def compose(name):
    Image, ImageDraw, ImageFont = _pil()
    title, rows = SHEETS[name]
    mono = ROOT / "tests" / "qml" / "fonts" / "LiberationMono-Regular.ttf"
    font = ImageFont.truetype(str(mono), 12)
    laid, width, y = [], 0, PAD + LABEL_H + GAP
    for row in rows:
        x, row_h = PAD, 0
        for scale, gid, cap in row:
            p = GOLDEN / scale / f"{gid}.png"
            im = Image.open(p).convert("RGB")
            laid.append((x, y, im, cap))
            x += max(im.width, len(cap) * 8) + GAP
            row_h = max(row_h, im.height)
        width = max(width, x - GAP + PAD)
        y += row_h + LABEL_H + GAP
    sheet = Image.new("RGB", (width, y + PAD - GAP), BG)
    d = ImageDraw.Draw(sheet)
    d.text((PAD, PAD), title, fill=FG, font=font)
    for x, py, im, cap in laid:
        sheet.paste(im, (x, py))
        d.text((x, py + im.height + 4), cap, fill=(140, 136, 130), font=font)
    return sheet


def encode(sheet, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    q = sheet.quantize(colors=128, method=0, dither=0)  # median cut
    q.save(path, optimize=True)
    if shutil.which("oxipng"):
        subprocess.run(["oxipng", "-q", "--strip", "all", "-o", "4",
                        "--alpha", str(path)], check=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    import tempfile
    bad = 0
    for name in SHEETS:
        dest = OUT / f"{name}.png"
        if a.check:
            with tempfile.TemporaryDirectory() as t:
                tmp = pathlib.Path(t) / dest.name
                encode(compose(name), tmp)
                if not dest.exists() or dest.read_bytes() != tmp.read_bytes():
                    print(f"readme_media: {dest.name} differs")
                    bad = 1
        else:
            encode(compose(name), dest)
            print(f"wrote {dest.relative_to(ROOT)} ({dest.stat().st_size} B)")
    return bad


if __name__ == "__main__":
    sys.exit(main())
