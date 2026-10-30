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
  [HL:x,y,w,h]        — highlight rect in screenshot px
A '['-terminated [POINT token whose coords don't parse is still stripped
(markup noise); a token with no closing ']' stays in the text, and
"[POINT" followed by anything other than ':', ' ', 'S' or ']' is not a
tag (e.g. "[POINTER]" passes through). RING/ARROW/HL are only tags when
the opener is immediately followed by ':' ("[HLS]" passes through); their
fields are plain ints (spaces ok), and a malformed tag, float or
non-positive size is stripped without a mark.

Source attribution: `[POINT:x,y:label(:screenN)]` and `[POINT:none]` tag
syntax ported/extended from farzaa/clicky CompanionManager.swift (MIT).
"""
from __future__ import annotations

import json
import math
import re
import shutil

MAX_POINTS = 32
MAX_DRAWINGS = 16  # per turn, all drawing kinds combined
MAX_LABEL = 80


# drawing tag opener -> (kind, int fields, positive-only fields)
_DRAW_TAGS = {
    "[RING:": ("ring", ("x", "y", "r"), ("r",)),
    "[ARROW:": ("arrow", ("x1", "y1", "x2", "y2"), ()),
    "[HL:": ("hl", ("x", "y", "w", "h"), ("w", "h")),
}
_OPENERS = ("[POINT",) + tuple(_DRAW_TAGS)


def _next_opener(text: str, pos: int = 0) -> tuple[int, str]:
    """(index, opener) of the earliest tag opener at or after `pos`,
    or (-1, "")."""
    best, found = -1, ""
    for op in _OPENERS:
        i = text.find(op, pos)
        if i >= 0 and (best < 0 or i < best):
            best, found = i, op
    return best, found


def _parse_drawing(opener: str, body: str) -> dict | None:
    """Payload for a drawing tag body ("1, 2,3"), or None if malformed."""
    kind, fields, positive = _DRAW_TAGS[opener]
    parts = body.split(",")
    if len(parts) != len(fields):
        return None
    try:
        vals = [int(v) for v in parts]
    except ValueError:
        return None
    d = {"kind": kind, **dict(zip(fields, vals))}
    if any(d[f] <= 0 for f in positive):
        return None
    return d


def extract_marked(text: str) -> tuple[str, list[tuple[int, dict]]]:
    """Like `extract`, but also report where each tag sat: returns
    (clean_text, [(offset, mark_px)]). `offset` is the tag's character
    position in clean_text; a [POINTS:[...]] list yields one mark per
    point, all at the same offset. A mark is a point payload (no "kind")
    or a drawing payload ("kind" ring/arrow/hl plus raw px fields), in
    one list in text order — a stable append-only prefix as text grows."""
    marks: list[tuple[int, dict]] = []
    points: list[dict] = []
    drawings = 0
    clean = []
    n = 0  # chars in `clean` so far

    def keep(s: str) -> None:
        nonlocal n
        clean.append(s)
        n += len(s)

    def add(x, y, label) -> None:
        before = len(points)
        _add(points, x, y, label)
        if len(points) > before:
            marks.append((n, points[-1]))

    rest = text
    while True:
        i, op = _next_opener(rest)
        if i < 0:
            keep(rest)
            break
        keep(rest[:i])
        tag = rest[i:]
        if op != "[POINT":
            e = tag.find("]")
            if e < 0:
                keep(tag)  # unclosed — leave visible
                break
            d = _parse_drawing(op, tag[len(op):e])
            if d is not None and drawings < MAX_DRAWINGS:
                drawings += 1
                marks.append((n, d))
            rest = tag[e + 1:]
            continue
        # not a tag unless the next char is ':', ' ', ']' or 'S'
        nxt = tag[6:7]
        if nxt and nxt not in ": ]S":
            keep(tag[:6])
            rest = tag[6:]
            continue
        if tag.startswith("[POINTS"):
            e = tag.find("]]")
            if e < 0:
                keep(tag)  # unclosed — leave visible
                break
            blob = tag[tag.find("[", 1):e + 1] if "[" in tag[1:e] else ""
            try:
                for p in json.loads(blob):
                    add(p.get("x"), p.get("y"), p.get("label", ""))
            except (json.JSONDecodeError, KeyError, TypeError,
                    ValueError, AttributeError):
                pass
            rest = tag[e + 2:]
            continue
        # [POINT:x,y:label]
        e = tag.find("]")
        if e < 0:
            keep(tag)  # unclosed — leave visible
            break
        body = tag[6:e].lstrip(": ")
        coords, _, label = body.partition(":")
        xy = coords.split(",")
        if len(xy) >= 2:
            try:
                add(int(xy[0]), int(xy[1]), label)
            except (ValueError, TypeError):
                pass
        rest = tag[e + 1:]
    joined = "".join(clean)
    out = joined.strip()
    lead = len(joined) - len(joined.lstrip())
    return out, [(min(max(o - lead, 0), len(out)), p) for o, p in marks]


def extract(text: str) -> tuple[str, list[dict]]:
    """Strip every tag kind from `text`; return (clean_text, points_px).
    Points keep screenshot-pixel coords: [{x, y, label}]; drawings are
    stripped and not returned (use `extract_marked`)."""
    clean, marks = extract_marked(text)
    return clean, [p for _, p in marks if "kind" not in p]


def strip_partial(text: str) -> str:
    """Cut a still-open trailing tag (or the start of one, like "[POI"
    or "[R") so streaming text never shows or speaks it. Closed tags and
    text without a partial tag come back unchanged."""
    pos = 0
    while True:
        i, op = _next_opener(text, pos)
        if i < 0:
            break
        tag = text[i:]
        if op == "[POINT":
            nxt = tag[6:7]
            if nxt and nxt not in ": ]S":
                pos = i + 6
                continue
            closer = "]]" if tag.startswith("[POINTS") else "]"
        else:
            closer = "]"
        e = tag.find(closer)
        if e < 0:
            return text[:i]
        pos = i + e + len(closer)
    for n in range(min(6, len(text)), 0, -1):
        if any(op.startswith(text[-n:]) for op in _OPENERS):
            return text[:-n]
    return text


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


def on_screen(x: int, y: int, mons: list[dict], margin: int = 2) -> bool:
    """Is the logical point (x, y) inside some monitor's logical rect?
    An unreadable layout (no monitors) says yes: no evidence, no veto.
    `margin` forgives rounding at the outer edges."""
    if not mons:
        return True
    for m in mons:
        s = _scale_of(m)
        x0, y0 = m.get("x", 0), m.get("y", 0)
        w, h = m.get("width", 0) / s, m.get("height", 0) / s
        if (x0 - margin <= x < x0 + w + margin
                and y0 - margin <= y < y0 + h + margin):
            return True
    return False


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


def _scaled(v: int, scale: float) -> int:
    return max(1, math.floor(v / scale + 0.5))


def drawings_to_logical(drawings_px: list[dict], mons: list[dict],
                        canvas: bool = False) -> list[dict]:
    """Map drawing marks (screenshot px, `kind` ring/arrow/hl) to
    logical coords. Anchors (ring center, both arrow ends, HL top-left)
    go through the same call points use: `canvas_to_logical` when
    `canvas` (image already logical: sizes unchanged), else `to_logical`,
    where ring r and HL w/h divide by the scale of the monitor holding
    the anchor (rounded, at least 1)."""
    conv = canvas_to_logical if canvas else to_logical
    out = []
    for d in drawings_px:
        kind = d.get("kind")
        if kind == "arrow":
            a, b = conv([{"x": d["x1"], "y": d["y1"]},
                         {"x": d["x2"], "y": d["y2"]}], mons)
            out.append({"kind": kind, "x1": a["x"], "y1": a["y"],
                        "x2": b["x"], "y2": b["y"]})
            continue
        if kind not in ("ring", "hl"):
            continue
        a = conv([{"x": d["x"], "y": d["y"]}], mons)[0]
        s = 1.0 if canvas else _map_px_point(d["x"], d["y"], mons)[2]
        if kind == "ring":
            out.append({"kind": kind, "x": a["x"], "y": a["y"],
                        "r": d["r"] if canvas else _scaled(d["r"], s)})
        else:
            out.append({"kind": kind, "x": a["x"], "y": a["y"],
                        "w": d["w"] if canvas else _scaled(d["w"], s),
                        "h": d["h"] if canvas else _scaled(d["h"], s)})
    return out
