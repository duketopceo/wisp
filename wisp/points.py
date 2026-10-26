"""[POINT:x,y:label] extraction + screenshot→logical coordinate mapping.

The model emits points in *screenshot pixel* coordinates (the image it
saw). grim composites outputs at logical_pos*scale (later outputs draw
over earlier on overlap), so a monitor at logical (x, y) with scale s
occupies the image rect (x*s, y*s, w_px, h_px). Hyprland/QML want
logical coordinates: logical = monitor.x + (px - monitor.x*s) / s.

Grammar (canonical, both cores):
  [POINT:x,y:label]   — x,y comma-separated ints; label optional
  [POINTS:[{x,y,label} ...]]  — JSON array, tag ends at "]]"
  [RING:x,y,r]        — ring target center + radius in screenshot px
  [ARROW:x1,y1,x2,y2] — arrow start + end in screenshot px
  [HL:x,y,w,h]        — highlight rect in screenshot px (fades ~2 s)
A '['-terminated [POINT token whose coords don't parse is still stripped
(markup noise); a token with no closing ']' stays in the text, and
"[POINT" followed by anything other than ':', ' ', 'S' or ']' is not a
tag (e.g. "[POINTER]" passes through).

Source attribution: `[POINT:x,y:label(:screenN)]` and `[POINT:none]` tag
syntax ported/extended from farzaa/clicky CompanionManager.swift (MIT).
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess

MAX_POINTS = 32
MAX_DRAWINGS = 64
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


# Backwards-compatible alias
extract_points = extract


def _scale_of(m: dict) -> float:
    """A monitor's scale, or 1.0 unless it is a finite positive number."""
    try:
        v = float(m.get("scale", 1) or 1)
    except (TypeError, ValueError):
        return 1.0
    return v if math.isfinite(v) and v > 0 else 1.0


def _split_screen_label(label, screen: int | None = None):
    """Move a trailing `:screenN` out of `label` -> (label, screen)."""
    lbl = str(label).strip()
    if screen is None and lbl:
        m = re.search(r":screen(\d+)\s*$", lbl)
        if m:
            screen = int(m.group(1))
            lbl = lbl[:m.start()].strip()
    return lbl, screen


def _add(points: list, x, y, label, screen: int | None = None) -> None:
    if len(points) >= MAX_POINTS:
        return
    lbl, screen = _split_screen_label(label, screen)
    item = {"x": int(x), "y": int(y), "label": lbl[:MAX_LABEL]}
    if screen is not None:
        item["screen"] = int(screen)
    points.append(item)


_DRAW_TAG_RE = re.compile(
    r"\[(?P<kind>POINTS|POINT|RING|ARROW|HL)(?P<sep>[:\s\]])"
)


def _map_px_point(x: int, y: int, mons: list[dict]) -> tuple[int, int, float]:
    """Map one screenshot-pixel (x, y) to (logical_x, logical_y, scale)."""
    for m in reversed(mons):
        s = _scale_of(m)
        ox, oy = m.get("x", 0) * s, m.get("y", 0) * s
        if (ox <= x < ox + m.get("width", 0)
                and oy <= y < oy + m.get("height", 0)):
            lx = m.get("x", 0) + math.floor((x - ox) / s + 0.5)
            ly = m.get("y", 0) + math.floor((y - oy) / s + 0.5)
            return int(lx), int(ly), s
    return int(x), int(y), 1.0


def _map_drawing_to_logical(d: dict, mons: list[dict]) -> dict:
    """Map a drawing primitive from grim composite pixels to logical coords."""
    if not mons:
        return dict(d)
    kind = d.get("kind") or d.get("type")
    out = dict(d)
    if kind == "point":
        lx, ly, _ = _map_px_point(d["x"], d["y"], mons)
        out["x"], out["y"] = lx, ly
    elif kind == "ring":
        lx, ly, s = _map_px_point(d["x"], d["y"], mons)
        out["x"], out["y"] = lx, ly
        out["r"] = max(1, math.floor(d["r"] / s + 0.5))
    elif kind == "arrow":
        x1, y1, _ = _map_px_point(d["x1"], d["y1"], mons)
        x2, y2, _ = _map_px_point(d["x2"], d["y2"], mons)
        out["x1"], out["y1"] = x1, y1
        out["x2"], out["y2"] = x2, y2
    elif kind == "hl":
        lx, ly, s = _map_px_point(d["x"], d["y"], mons)
        out["x"], out["y"] = lx, ly
        out["w"] = max(1, math.floor(d["w"] / s + 0.5))
        out["h"] = max(1, math.floor(d["h"] / s + 0.5))
    return out


def extract_drawings(text: str,
                     monitors: list[dict] | None = None) -> tuple[str, list[dict]]:
    """Extract `[POINT:x,y:label]`, `[RING:x,y,r]`, `[ARROW:x1,y1,x2,y2]`,
    and `[HL:x,y,w,h]` tags from `text`.

    When `monitors` is provided, maps grim composite pixel coordinates to
    Hyprland logical coordinates (including scaling `r` and `w`/`h` by the
    containing monitor's scale). When `monitors` is None, preserves raw
    screenshot-pixel coordinates.

    Returns `(clean_text, drawings)`.
    """
    drawings: list[dict] = []
    clean: list[str] = []
    rest = text or ""

    while rest:
        m = _DRAW_TAG_RE.search(rest)
        if not m:
            clean.append(rest)
            break
        start = m.start()
        kind = m.group("kind")
        clean.append(rest[:start])
        tag = rest[start:]

        if kind == "POINTS":
            e = tag.find("]]")
            if e < 0:
                clean.append(tag)
                break
            blob = tag[tag.find("[", 1):e + 1] if "[" in tag[1:e] else ""
            try:
                for p in json.loads(blob):
                    if len(drawings) < MAX_DRAWINGS:
                        px = int(p.get("x"))
                        py = int(p.get("y"))
                        lbl, scr = _split_screen_label(p.get("label", ""))
                        item = {
                            "kind": "point",
                            "type": "point",
                            "x": px,
                            "y": py,
                            "label": lbl[:MAX_LABEL],
                        }
                        if scr is not None:
                            item["screen"] = scr
                        drawings.append(item)
            except (json.JSONDecodeError, KeyError, TypeError,
                    ValueError, AttributeError):
                pass
            rest = tag[e + 2:]
            continue

        e = tag.find("]")
        if e < 0:
            clean.append(tag)
            break

        prefix_len = 1 + len(kind)
        body = tag[prefix_len:e].lstrip(": ")

        if len(drawings) < MAX_DRAWINGS:
            if kind == "POINT":
                if body.strip().lower() != "none":
                    coords, _, label = body.partition(":")
                    xy = coords.split(",")
                    if len(xy) >= 2:
                        try:
                            px, py = int(xy[0].strip()), int(xy[1].strip())
                            lbl = label.strip()
                            lbl, screen = _split_screen_label(lbl)
                            item = {
                                "kind": "point",
                                "type": "point",
                                "x": px,
                                "y": py,
                                "label": lbl[:MAX_LABEL],
                            }
                            if screen is not None:
                                item["screen"] = screen
                            drawings.append(item)
                        except (ValueError, TypeError):
                            pass
            elif kind == "RING":
                parts = body.partition(":")[0].split(",")
                if len(parts) >= 3:
                    try:
                        px = int(parts[0].strip())
                        py = int(parts[1].strip())
                        r = int(parts[2].strip())
                        if r > 0:
                            drawings.append({
                                "kind": "ring",
                                "type": "ring",
                                "x": px,
                                "y": py,
                                "r": r,
                            })
                    except (ValueError, TypeError):
                        pass
            elif kind == "ARROW":
                parts = body.partition(":")[0].split(",")
                if len(parts) >= 4:
                    try:
                        x1 = int(parts[0].strip())
                        y1 = int(parts[1].strip())
                        x2 = int(parts[2].strip())
                        y2 = int(parts[3].strip())
                        drawings.append({
                            "kind": "arrow",
                            "type": "arrow",
                            "x1": x1,
                            "y1": y1,
                            "x2": x2,
                            "y2": y2,
                        })
                    except (ValueError, TypeError):
                        pass
            elif kind == "HL":
                parts = body.partition(":")[0].split(",")
                if len(parts) >= 4:
                    try:
                        px = int(parts[0].strip())
                        py = int(parts[1].strip())
                        w = int(parts[2].strip())
                        h = int(parts[3].strip())
                        if w > 0 and h > 0:
                            drawings.append({
                                "kind": "hl",
                                "type": "hl",
                                "x": px,
                                "y": py,
                                "w": w,
                                "h": h,
                                "fade_ms": 2000,
                            })
                    except (ValueError, TypeError):
                        pass

        rest = tag[e + 1:]

    if monitors is not None:
        drawings = [_map_drawing_to_logical(d, monitors) for d in drawings]

    return "".join(clean).strip(), drawings


def strip_drawing_tags(text: str) -> str:
    """Return `text` with all closed POINT/POINTS/RING/ARROW/HL tags stripped."""
    clean, _ = extract_drawings(text, monitors=None)
    return clean


def monitors() -> list[dict]:
    """[{x, y, width, height, scale}] via the platform adapter —
    the Hyprland socket. Empty on failure."""
    from . import platform
    return platform.monitors()


def logical_bbox(mons: list[dict]) -> tuple:
    """(x, y, w, h) bounding box of the monitor layout in *logical*
    coords — each monitor contributes x, y, w/scale, h/scale."""
    if not mons:
        return 0, 0, 0, 0
    x0 = min(m.get("x", 0) for m in mons)
    y0 = min(m.get("y", 0) for m in mons)
    x1 = max(m.get("x", 0) + m.get("width", 0)
             / _scale_of(m) for m in mons)
    y1 = max(m.get("y", 0) + m.get("height", 0)
             / _scale_of(m) for m in mons)
    return int(x0), int(y0), round(x1 - x0), round(y1 - y0)


def img_space_is_logical() -> bool:
    """True when screenshots are normalized to the logical canvas —
    magick is present to resize, or every monitor is scale 1 anyway.
    When True, model-emitted image pixels are already logical coords."""
    if shutil.which("magick"):
        return True
    return all(_scale_of(m) == 1.0
               for m in monitors())


SHOT_ORIGIN: tuple | None = None
"""Logical (x,y) origin of the most recent normalized screenshot —
set by the screenshot tool; falls back to the canvas bbox origin."""


def canvas_to_logical(points_img: list[dict],
                      mons: list[dict]) -> list[dict]:
    """Map points in *normalized* image space to logical coords —
    the shot's logical origin offset."""
    if SHOT_ORIGIN is not None:
        ox, oy = SHOT_ORIGIN
    else:
        ox, oy, _, _ = logical_bbox(mons)
    return [{**p, "x": p["x"] + ox, "y": p["y"] + oy}
            for p in points_img]


def to_logical(points_px: list[dict], mons: list[dict]) -> list[dict]:
    """Map screenshot-pixel points to Hyprland logical coords. Points
    outside every monitor rect pass through 1:1 (scale 1 assumed)."""
    out = []
    for p in points_px:
        x, y = p["x"], p["y"]
        placed = False
        # grim draws outputs in order — on overlap the LAST wins
        for m in reversed(mons):
            s = _scale_of(m)
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
