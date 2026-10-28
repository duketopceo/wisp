"""Blank or protected capture detection (B28).

A window can hand back a black or single-colour frame (DRM video, a
protected surface, a compositor that refuses). Answering as if that
frame were the screen is a lie, so the frame is checked after capture:

1. blank -> retry once as a window capture;
2. still blank -> read the focused window's accessibility text and say
   in one sentence what happened;
3. nothing to read -> end the turn with "I can't see that window"
   without asking a model about content nobody saw.

The test is a luma histogram, so a real dark UI (text, borders, panels)
is never flagged: it has many distinct levels, a blank frame has one.
Backends, in order: ImageMagick `magick` (already needed for the
screenshot shrink), Pillow, then a bounded pure-Python PNG reader that
only runs on small images. When none can read the frame the verdict is
"unknown", which is treated as not blank: never a false alarm.
"""
import pathlib
import re
import shutil
import subprocess
import zlib
from collections import Counter

BAND = 2             # luma levels counted as "the same colour"
SINGLE = 0.9995      # share of one colour that is a blank frame
BLACK_MAX = 6        # darkest levels: a true black, not a dark theme
BLACK_SHARE = 0.995  # near-black frame, allowing a cursor or a caret
MINOR = 0.0005       # a level holding this share is real content
PURE_PY_MAX = 6_000_000   # raw bytes the pure-Python reader will decode
TEXT_CAP = 2000

LINE_READING = ("That window blocks screenshots, so I'm reading its text "
                "instead.")
LINE_BLIND = "I can't see that window."


class Blind:
    """The screenshot of this turn was blank and could not be recovered.
    Falsy, so a caller that only tests for a shot treats it as no shot."""

    def __init__(self, reason: str, retried: bool = False):
        self.reason = reason
        self.retried = retried

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"Blind({self.reason!r})"


# -- reading the frame ------------------------------------------------

def _magick_levels(path) -> dict | None:
    magick = shutil.which("magick")
    if not magick:
        return None
    try:
        r = subprocess.run(
            [magick, str(path), "-colorspace", "Gray", "-depth", "8",
             "-format", "%c", "histogram:info:-"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = {}
    for m in re.finditer(r"^\s*(\d+):\s*\(\s*(\d+)", r.stdout, re.M):
        n, v = int(m.group(1)), int(m.group(2))
        out[v] = out.get(v, 0) + n
    return out or None


def _pil_levels(path) -> dict | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            hist = im.convert("L").histogram()
    except Exception:
        return None
    return {i: n for i, n in enumerate(hist) if n} or None


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _png_levels(path) -> dict | None:
    """Luma histogram of an 8-bit, non-interlaced PNG (what grim and the
    shrink step write). None for anything else or anything large."""
    try:
        data = pathlib.Path(path).read_bytes()
    except OSError:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, hdr = 8, [], None
    while pos + 8 <= len(data):
        n = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            hdr = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if hdr is None or not idat:
        return None
    w = int.from_bytes(hdr[0:4], "big")
    h = int.from_bytes(hdr[4:8], "big")
    depth, ctype, interlace = hdr[8], hdr[9], hdr[12]
    bpp = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or interlace or bpp is None or w * h * bpp > PURE_PY_MAX:
        return None
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None
    stride = w * bpp
    if len(raw) < h * (stride + 1):
        return None
    prev = bytearray(stride)
    counts = Counter()
    for y in range(h):
        base = y * (stride + 1)
        f = raw[base]
        row = bytearray(raw[base + 1:base + 1 + stride])
        if f == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 255
        elif f == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + _paeth(a, prev[i], c)) & 255
        elif f != 0:
            return None
        if ctype in (0, 4):
            counts.update(row[0::bpp])
        else:
            counts.update(zip(row[0::bpp], row[1::bpp], row[2::bpp]))
        prev = row
    if ctype in (0, 4):
        return dict(counts)
    out = {}
    for (r, g, b), n in counts.items():
        v = (r * 299 + g * 587 + b * 114) // 1000
        out[v] = out.get(v, 0) + n
    return out


def levels(path) -> dict | None:
    """{luma 0..255: pixel count}, or None when the frame can't be read."""
    for fn in (_magick_levels, _pil_levels, _png_levels):
        got = fn(path)
        if got:
            return got
    return None


# -- the verdict ------------------------------------------------------

def verdict(hist: dict | None) -> str:
    """'' for a frame with content (or one we can't judge), else a
    plain word for what the blank frame is."""
    total = sum((hist or {}).values())
    if not total:
        return ""
    dom = max(hist, key=hist.get)
    near = sum(n for v, n in hist.items() if abs(v - dom) <= BAND)
    share = near / total
    minor = sum(1 for v, n in hist.items()
                if abs(v - dom) > BAND and n / total >= MINOR)
    word = ("black" if dom <= BLACK_MAX else
            "white" if dom >= 255 - BAND else "a single colour")
    if share >= SINGLE:
        return word
    if dom <= BLACK_MAX and share >= BLACK_SHARE and minor <= 2:
        return "black"
    return ""


def blank_reason(path) -> str:
    """Why this frame is blank ('black', 'white', 'a single colour') or
    '' when it has content or can't be read. Never raises."""
    try:
        if path is None or not pathlib.Path(path).is_file():
            return ""
        return verdict(levels(path))
    except Exception:
        return ""


def vet(png, retry=None, trace=None):
    """The frame to use for the turn: `png` when it has content; else
    the window-capture retry when that has; else a Blind. `retry` is a
    callable returning a path or None; `trace` gets (event, fields)."""
    if png is None:
        return None
    why = blank_reason(png)
    if not why:
        return png
    if trace:
        trace("screen_blank", {"why": why})
    try:
        pathlib.Path(png).unlink(missing_ok=True)
    except OSError:
        pass
    again = None
    if retry is not None:
        try:
            again = retry()
        except Exception:
            again = None
    if again is not None:
        why2 = blank_reason(again)
        if not why2:
            if trace:
                trace("screen_blank_recovered", {"via": "window"})
            return again
        try:
            pathlib.Path(again).unlink(missing_ok=True)
        except OSError:
            pass
    return Blind(why, retried=again is not None)


# -- the fallback: the window's own text --------------------------------

_TEXT_KEYS = ("name", "label", "title", "value", "text", "description")
_TREE_KEYS = ("tree", "accessibility_tree", "accessibility", "ax_tree",
              "elements", "nodes", "children", "root")


def _flatten(node, out: list, depth: int = 0) -> None:
    if depth > 40 or len(out) > 400:
        return
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, list):
        for n in node:
            _flatten(n, out, depth + 1)
    elif isinstance(node, dict):
        for k in _TEXT_KEYS:
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                out.append(v)
        for k in _TREE_KEYS:
            if k in node:
                _flatten(node[k], out, depth + 1)


def _tidy(parts: list, cap: int = TEXT_CAP) -> str:
    seen, lines = set(), []
    for p in parts:
        for line in str(p).splitlines():
            line = " ".join(line.split())
            if len(line) < 2 or line in seen:
                continue
            seen.add(line)
            lines.append(line[:300])
    return "\n".join(lines)[:cap]


def window_text(win: dict | None, client=None) -> str:
    """The focused window's accessibility text through the cua driver
    ('' when there is no driver, no window or nothing to read)."""
    if not win:
        return ""
    try:
        from . import observe
        c = client if client is not None else observe._cua_client()
        if c is None:
            return ""
        w = observe._pick_window(c, win)
        if not w:
            return ""
        args = {"window_id": int(w.get("window_id", w.get("id", 0))),
                "include_accessibility_tree": True,
                "include_screenshot": False}
        if w.get("pid") is not None:
            args["pid"] = int(w["pid"])
        from . import record
        res = c.call("get_window_state", args, timeout=8.0,
                     session=record.SESSION)
    except Exception:
        return ""
    parts: list = []
    _flatten(res, parts)
    return _tidy(parts)


def context_note(reason: str, text: str) -> str:
    """What the model is told when the screen could not be captured."""
    return ("[screen] The screenshot of the focused window came out "
            f"{reason} (the window blocks capture). You cannot see it: "
            "answer only from the window text below, and say so if the "
            "question needs the picture.\n[window text]\n" + text)
