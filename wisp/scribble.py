"""Scribble to ask (B7): circle the thing, then say "what is this".

While the talk key is held the overlay lets the user drag on the screen;
the strokes reach the daemon through `wispd scribble set` (a small file in
the runtime dir, never part of the IPC state). When the turn takes its
screenshot the strokes are drawn into the picture the model sees and the
model is told they are the user's own marks. They are consumed by that
one turn: read once, deleted, ignored when stale.

Coordinates are screen pixels as the overlay sees them (`w` x `h`); the
drawing scales them to the screenshot, which is the logical-size image.
Pure Pillow, and it degrades to "no scribble" when Pillow is missing or
the shot is unreadable.
"""
import base64
import io
import json
import math
import os
import time

from . import config

MAX_STROKES = 12
MAX_POINTS = 240
MAX_AGE_S = 60.0
MAX_DIM = 16384
STROKE_RGB = (255, 45, 120)      # the user's marks: loud on any screen
HALO_RGB = (255, 255, 255)


def path():
    return config.RUN_DIR / "scribble.json"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def normalize(doc) -> dict | None:
    """Validated {strokes, w, h}, or None when nothing drawable is left."""
    if not isinstance(doc, dict):
        return None
    w, h = _num(doc.get("w")), _num(doc.get("h"))
    if not w or not h or not (0 < w <= MAX_DIM and 0 < h <= MAX_DIM):
        return None
    strokes = []
    raw = doc.get("strokes")
    for s in (raw if isinstance(raw, list) else [])[-MAX_STROKES:]:
        pts = []
        for p in (s if isinstance(s, list) else [])[:MAX_POINTS]:
            if isinstance(p, (list, tuple)) and len(p) == 2:
                x, y = _num(p[0]), _num(p[1])
                if x is not None and y is not None:
                    pts.append([min(max(x, 0.0), w), min(max(y, 0.0), h)])
        if len(pts) >= 2:
            strokes.append(pts)
    return {"strokes": strokes, "w": w, "h": h} if strokes else None


def save(doc, now=None) -> dict:
    """Store the strokes for the next turn (replacing any earlier ones).
    An empty or invalid doc clears. Returns {strokes, points}."""
    good = normalize(doc)
    if good is None:
        clear()
        return {"strokes": 0, "points": 0}
    good["at"] = time.time() if now is None else now
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(good, f)
    os.replace(tmp, p)
    return {"strokes": len(good["strokes"]),
            "points": sum(len(s) for s in good["strokes"])}


def clear() -> None:
    try:
        path().unlink()
    except FileNotFoundError:
        pass


def take(now=None) -> dict | None:
    """The stored strokes, once: the file is deleted either way, and a
    doc older than MAX_AGE_S (a turn that never used it) is ignored."""
    p = path()
    try:
        raw = json.loads(p.read_text())
    except (OSError, ValueError):
        raw = None
    clear()
    doc = normalize(raw)
    if doc is None:
        return None
    at = _num(raw.get("at")) if isinstance(raw, dict) else None
    now = time.time() if now is None else now
    if at is None or now - at > MAX_AGE_S or at > now + 5:
        return None
    return doc


def bbox(doc: dict, img_w: int, img_h: int) -> tuple:
    """(x0, y0, x1, y1) of the strokes in screenshot pixels."""
    sx, sy = img_w / doc["w"], img_h / doc["h"]
    xs = [p[0] * sx for s in doc["strokes"] for p in s]
    ys = [p[1] * sy for s in doc["strokes"] for p in s]
    return (round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys)))


def hint(box: tuple, n: int) -> str:
    return (f"The user drew {n} stroke{'s' if n != 1 else ''} on the "
            "screenshot while asking, in bright pink with a white edge, "
            f"around x {box[0]}-{box[2]}, y {box[1]}-{box[3]}. What they "
            "circled or underlined is what 'this', 'it' or 'here' means; "
            "the pink is their mark, not part of the app.")


def apply(shot_b64: str | None, doc: dict | None):
    """(shot with the strokes drawn in, hint text). The shot is returned
    untouched with an empty hint when there is nothing to draw or the shot
    cannot be read. Same encoding in as out (data URL or raw base64)."""
    if not shot_b64 or not doc:
        return shot_b64, ""
    from . import ink
    img = ink.open_image(shot_b64)
    if img is None:
        return shot_b64, ""
    try:
        from PIL import ImageDraw
        base = img.convert("RGB")
        draw = ImageDraw.Draw(base)
        k = max(base.width / doc["w"], base.height / doc["h"])
        width = max(3, round(4 * k))
        for s in doc["strokes"]:
            pts = [(p[0] * base.width / doc["w"],
                    p[1] * base.height / doc["h"]) for p in s]
            for color, w in ((HALO_RGB, width + 4), (STROKE_RGB, width)):
                draw.line(pts, fill=color, width=w, joint="curve")
                r = w / 2
                for x, y in (pts[0], pts[-1]):
                    draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        buf = io.BytesIO()
        head = shot_b64[:30].lower()
        jpeg = head.startswith("data:image/jpeg") or head.startswith(
            "data:image/jpg")
        if jpeg:
            base.save(buf, "JPEG", quality=88)
        else:
            base.save(buf, "PNG")
        enc = base64.b64encode(buf.getvalue()).decode()
        if shot_b64.startswith("data:"):
            enc = f"data:image/{'jpeg' if jpeg else 'png'};base64,{enc}"
        return enc, hint(bbox(doc, base.width, base.height),
                         len(doc["strokes"]))
    except Exception:
        return shot_b64, ""
