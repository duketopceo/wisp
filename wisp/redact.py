"""Whole-screen privacy (B9): blank every sensitive window in a screenshot.

The focused-window rule (`cua_safety.capture_blocked`) refuses to take a
screenshot while a password manager, keyring prompt or sudo terminal has
focus. A banking or vault window sitting BEHIND the focused one would still
ride into the model payload, so after the shot is taken every mapped,
visible window that matches the same deny policy is painted over. If such a
window is visible and cannot be painted over (no image library, unreadable
shot), the screenshot is refused instead. Focused-only handling is a strict
subset: with nothing but the focused window to hide, nothing here changes.

Coordinates: Hyprland client rects are logical; the shot is scaled from the
logical bounding box of the captured outputs to the image size.
"""
import pathlib
import shutil
import subprocess

from . import cua_safety


def rects(cfg, clients=None, monitors=None) -> tuple:
    """([(x, y, w, h) logical, ...], readable) for every visible sensitive
    window. readable=False when the compositor's window list could not be
    read."""
    from . import verify
    found, readable = verify.visible_deny_all(cfg, clients, monitors)
    out = []
    for c in found:
        at, size = c.get("at"), c.get("size")
        try:
            x, y = float(at[0]), float(at[1])
            w, h = float(size[0]), float(size[1])
        except (TypeError, ValueError, IndexError):
            continue
        if w > 0 and h > 0:
            out.append((x, y, w, h))
    return out, readable


def _bbox(monitors, output):
    from . import points
    mons = monitors if monitors is not None else points.monitors()
    if output:
        m = next((m for m in mons if m.get("name") == output), None)
        if not m:
            return None
        s = float(m.get("scale", 1) or 1)
        return (m.get("x", 0), m.get("y", 0),
                round(m.get("width", 0) / s), round(m.get("height", 0) / s))
    return points.logical_bbox(mons)


def _to_pixels(rect, bbox, img_w, img_h):
    bx, by, bw, bh = bbox
    sx, sy = img_w / bw, img_h / bh
    x, y, w, h = rect
    x0 = max(0, int((x - bx) * sx))
    y0 = max(0, int((y - by) * sy))
    x1 = min(img_w, int(round((x + w - bx) * sx)))
    y1 = min(img_h, int(round((y + h - by) * sy)))
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def blank(path, boxes) -> bool:
    """Paint each (x0, y0, x1, y1) pixel box black in the image at
    `path`, in place. False when it could not be done."""
    path = pathlib.Path(path)
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        Image = None
    if Image is not None:
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                d = ImageDraw.Draw(im)
                for x0, y0, x1, y1 in boxes:
                    d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(0, 0, 0))
                im.save(path, format="PNG")
            return True
        except (OSError, ValueError):
            return False
    magick = shutil.which("magick")
    if not magick:
        return False
    draw = " ".join(f"rectangle {x0},{y0} {x1 - 1},{y1 - 1}"
                    for x0, y0, x1, y1 in boxes)
    try:
        r = subprocess.run([magick, str(path), "-fill", "black",
                            "-draw", draw, str(path)],
                           capture_output=True, timeout=15)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        pass
    try:
        import struct
        with open(path, "rb") as f:
            head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except OSError:
        pass
    return None


def apply(path, cfg=None, *, output=None, clients=None,
          monitors=None) -> str:
    """Blank every visible sensitive window in the shot at `path`.
    Returns "" when the shot is safe to use (nothing to hide, or hidden)
    and a reason when it must be discarded. Off with `[cua] safety =
    false`."""
    if not cua_safety.settings(cfg)["safety"]:
        return ""
    found, readable = rects(cfg, clients, monitors)
    if not found:
        return ""
    size, bbox = _size(path), None
    try:
        bbox = _bbox(monitors, output)
    except Exception:
        bbox = None
    if not size or not bbox or not bbox[2] or not bbox[3]:
        return "a sensitive window is visible and the shot could not be mapped"
    boxes = [b for b in (_to_pixels(r, bbox, *size) for r in found) if b]
    if not boxes:
        return ""          # every sensitive window is off the captured area
    if not blank(path, boxes):
        return "a sensitive window is visible and could not be blanked"
    return ""
