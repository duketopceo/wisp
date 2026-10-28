"""Tone under a mark (B4): is the screen light or dark where Wisp draws?

The overlay picks its glow (and any text it puts on a mark) from this, so
ink reads on any background. The sample comes from the press-time
screenshot the model saw, so marks and sample share one coordinate space
(screenshot pixels). Pure Pillow; the same WCAG luminance and 0.179
crossover as shell-plugin/lib/ink.js (a parity test keeps them equal).
"""
import base64
import io

LIGHT_BELOW = 0.179   # white and black text have equal contrast here
POINT_BOX = 40        # px square sampled around a point or an arrow tip


def _channel(v: float) -> float:
    c = max(0.0, min(255.0, v)) / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(r: float, g: float, b: float) -> float:
    """WCAG relative luminance of an sRGB colour (0..255 channels)."""
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def tone(lum: float) -> str:
    return "dark" if lum < LIGHT_BELOW else "light"


def text_on(lum: float) -> str:
    """Text colour that reads on that luminance: light on dark."""
    return "light" if lum < LIGHT_BELOW else "dark"


def mean_luminance(img, box) -> float | None:
    """Mean luminance of `box` (x, y, w, h) of a PIL image, clamped to the
    image; None when the box misses it."""
    x, y, w, h = box
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(img.width, int(x + w + 0.999)), min(img.height,
                                                       int(y + h + 0.999))
    if x1 <= x0 or y1 <= y0:
        return None
    from PIL import Image
    px = img.convert("RGB").crop((x0, y0, x1, y1))
    side = (min(px.width, 48), min(px.height, 48))   # box-average, don't walk 4K
    if side != px.size:
        px = px.resize(side, Image.BOX)
    data = px.tobytes()
    n = len(data) // 3
    total = sum(luminance(data[i], data[i + 1], data[i + 2])
                for i in range(0, n * 3, 3))
    return total / n if n else None


def box_for(mark: dict):
    """The screen area a mark sits on, in the mark's own pixels."""
    kind = mark.get("kind")
    try:
        if kind == "ring":
            r = float(mark["r"])
            return (mark["x"] - r, mark["y"] - r, 2 * r, 2 * r)
        if kind == "hl":
            return (mark["x"], mark["y"], mark["w"], mark["h"])
        if kind == "arrow":
            s = POINT_BOX
            return (mark["x2"] - s / 2, mark["y2"] - s / 2, s, s)
        if "x" in mark and "y" in mark:
            s = POINT_BOX
            return (mark["x"] - s / 2, mark["y"] - s / 2, s, s)
    except (KeyError, TypeError, ValueError):
        return None
    return None


def open_image(shot_b64: str | None):
    """PIL image from the model's screenshot (raw base64 or a data URL);
    None when absent or unreadable."""
    if not shot_b64:
        return None
    try:
        from PIL import Image
        data = shot_b64.split(",", 1)[1] if shot_b64.startswith("data:") \
            else shot_b64
        img = Image.open(io.BytesIO(base64.b64decode(data)))
        img.load()
        return img
    except Exception:
        return None


def tones_for(img, marks: list) -> list:
    """One tone ("light", "dark" or "" when unknown) per mark."""
    out = []
    for m in marks:
        box = box_for(m) if img is not None else None
        lum = mean_luminance(img, box) if box else None
        out.append(tone(lum) if lum is not None else "")
    return out
