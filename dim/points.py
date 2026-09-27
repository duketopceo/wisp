"""[POINT:x,y:label] extraction + screenshot→logical coordinate mapping.

The model emits points in *screenshot pixel* coordinates (the image it
saw). grim composites outputs at logical_pos*scale (later outputs draw
over earlier on overlap), so a monitor at logical (x, y) with scale s
occupies the image rect (x*s, y*s, w_px, h_px). Hyprland/QML want
logical coordinates: logical = monitor.x + (px - monitor.x*s) / s.

Grammar (canonical, both cores):
  [POINT:x,y:label]   — x,y comma-separated ints; label optional
  [POINTS:[{x,y,label} ...]]  — JSON array, tag ends at "]]"
A '['-terminated [POINT token whose coords don't parse is still stripped
(markup noise); a token with no closing ']' stays in the text, and
"[POINT" followed by anything other than ':', ' ', 'S' or ']' is not a
tag (e.g. "[POINTER]" passes through).
"""
import json
import math
import shutil
import subprocess

MAX_POINTS = 32
MAX_LABEL = 80


def extract(text: str) -> tuple[str, list[dict]]:
    """Strip point tags from `text`; return (clean_text, points_px).
    Points keep screenshot-pixel coords: [{x, y, label}]."""
    points = []
    clean = []
    rest = text
    while True:
        i = rest.find("[POINT")
        if i < 0:
            clean.append(rest)
            break
        clean.append(rest[:i])
        tag = rest[i:]
        # not a tag unless the next char is ':', ' ', ']' or 'S'
        nxt = tag[6:7]
        if nxt and nxt not in ": ]S":
            clean.append(tag[:6])
            rest = tag[6:]
            continue
        if tag.startswith("[POINTS"):
            e = tag.find("]]")
            if e < 0:
                clean.append(tag)  # unclosed — leave visible
                break
            blob = tag[tag.find("[", 1):e + 1] if "[" in tag[1:e] else ""
            try:
                for p in json.loads(blob):
                    _add(points, p.get("x"), p.get("y"),
                         p.get("label", ""))
            except (json.JSONDecodeError, KeyError, TypeError,
                    ValueError, AttributeError):
                pass
            rest = tag[e + 2:]
            continue
        # [POINT:x,y:label]
        e = tag.find("]")
        if e < 0:
            clean.append(tag)  # unclosed — leave visible
            break
        body = tag[6:e].lstrip(": ")
        coords, _, label = body.partition(":")
        xy = coords.split(",")
        if len(xy) >= 2:
            try:
                _add(points, int(xy[0]), int(xy[1]), label)
            except (ValueError, TypeError):
                pass
        rest = tag[e + 1:]
    return "".join(clean).strip(), points


def _add(points: list, x, y, label) -> None:
    if len(points) >= MAX_POINTS:
        return
    points.append({"x": int(x), "y": int(y),
                   "label": str(label).strip()[:MAX_LABEL]})


def monitors() -> list[dict]:
    """hyprctl monitors -j → [{x, y, width, height, scale}] (physical px
    width/height, logical x/y, fractional scale). Empty on failure."""
    if not shutil.which("hyprctl"):
        return []
    from .pipeline import hypr_env  # lazy: keeps module free of pipeline
    try:
        r = subprocess.run(["hyprctl", "monitors", "-j"],
                           capture_output=True, text=True, timeout=5,
                           env=hypr_env())
        return json.loads(r.stdout) if r.returncode == 0 else []
    except Exception:
        return []


def to_logical(points_px: list[dict], mons: list[dict]) -> list[dict]:
    """Map screenshot-pixel points to Hyprland logical coords. Points
    outside every monitor rect pass through 1:1 (scale 1 assumed)."""
    out = []
    for p in points_px:
        x, y = p["x"], p["y"]
        placed = False
        # grim draws outputs in order — on overlap the LAST wins
        for m in reversed(mons):
            s = float(m.get("scale", 1) or 1)
            ox, oy = m.get("x", 0) * s, m.get("y", 0) * s
            if (ox <= x < ox + m.get("width", 0)
                    and oy <= y < oy + m.get("height", 0)):
                out.append({**p,
                            "x": m.get("x", 0)
                            + math.floor((x - ox) / s + 0.5),
                            "y": m.get("y", 0)
                            + math.floor((y - oy) / s + 0.5)})
                placed = True
                break
        if not placed:
            out.append(dict(p))
    return out
