"""
UI grounding adapter (W13, backend U12): target name -> screen point.

Extends the Decision-Agent grounding engine (#77: Clef/Jev `noul`
probabilistic centering, kept below as the vision-LLM fallback) into a
provider chain with one typed result:

    control app control channel `ui.elements` (FilmCraft first; exact,
            no pixels — wisp/control.py, U3/KTD3)
    a11y    cua `get_window_state` element tree (exact, no pixels)
    uitars  local UI-TARS on llama-server 127.0.0.1:8081 (loopback only)
    jev     #77's noul patch grounding (existing default; slow fallback)

`ground_target()` returns a `Target(x, y, frame, confidence, source)`
whose frame is always compositor-global (== Hyprland logical px), or
raises `GroundRefused`. A candidate under `[ground] min_confidence`
triggers exactly one re-observe (fresh capture, whole chain again); if
that is still low the target is refused: a low-confidence point is
never clicked. Provider failures are contained: a provider returns None
(malformed / not found), raises `Skip` (not applicable) or
`ProviderDown` (unreachable), and nothing else reaches the caller.

Frames: `shot` = grim canvas pixels (scale = max monitor scale, origin =
layout bbox, or one monitor for a single-output capture); `canvas` =
normalised logical image + origin; `global`/`logical` = identity.
"""
from __future__ import annotations

import base64
import dataclasses
import io
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple

from . import config

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


# ---------------------------------------------------------------- types

class GroundRefused(Exception):
    """Grounding gave no clickable target. `code` is a closed U7 code
    (ground_failed | ground_down); `reason` is not_found | low_confidence
    | all_down | no_capture | empty."""

    def __init__(self, code: str, reason: str = "", detail: str = ""):
        self.code, self.reason, self.detail = code, reason, detail
        super().__init__(f"{code}: {reason} {detail}".strip())


class ProviderDown(Exception):
    """A provider's backend is unreachable."""


class Skip(Exception):
    """A provider does not apply here (not configured / not available)."""


@dataclasses.dataclass
class Candidate:
    x: float
    y: float
    confidence: float
    source: str
    frame: str = "shot"
    size: tuple | None = None      # (w, h) of the image the model saw
    label: str = ""
    window: str = ""
    rect: tuple | None = None      # element bounds (x,y,w,h) in `frame`


@dataclasses.dataclass(frozen=True)
class Target:
    x: int
    y: int
    frame: str
    confidence: float
    source: str
    label: str = ""
    window: str = ""
    rect: tuple | None = None      # element bounds (x,y,w,h) in `frame`

    @property
    def element_backed(self) -> bool:
        """Only observed control/tree bounds count, not a model's label."""
        return self.frame in ("global", "logical") \
            and self.source in ("control", "a11y") \
            and _contains(self.rect, self.x, self.y)


class Shot:
    """One screen capture: full-resolution PNG b64 + its pixel size."""

    def __init__(self, b64: str, width: int, height: int):
        self.b64, self.width, self.height = b64, int(width), int(height)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Shot | None":
        if _PIL_AVAILABLE:
            try:
                w, h = Image.open(io.BytesIO(raw)).size
            except Exception:
                return None
        else:
            import struct
            if raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
                return None
            w, h = struct.unpack(">II", raw[16:24])
        return cls(base64.b64encode(raw).decode(), w, h) if w and h else None

    def scaled(self, max_side: int):
        """(b64, w, h) with the long side capped at max_side. Providers
        downscale big images server-side to an unknowable size; sending a
        known size keeps their coordinates mappable."""
        longest = max(self.width, self.height)
        if not _PIL_AVAILABLE or max_side <= 0 or longest <= max_side:
            return self.b64, self.width, self.height
        k = max_side / float(longest)
        w, h = max(1, round(self.width * k)), max(1, round(self.height * k))
        try:
            im = Image.open(io.BytesIO(base64.b64decode(self.b64)))
            buf = io.BytesIO()
            im.convert("RGB").resize((w, h)).save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode(), w, h
        except Exception:
            return self.b64, self.width, self.height

    def resized_pointing(self) -> tuple[str, int, int]:
        """Resize screenshot to the closest Clicky pointing resolution
        (`1024x768`, `1280x800`, or `1366x768`) for single-pass VLM pointing."""
        rw, rh = pick_pointing_resolution(self.width, self.height)
        if (self.width, self.height) == (rw, rh) or not _PIL_AVAILABLE:
            return self.b64, self.width, self.height
        try:
            im = Image.open(io.BytesIO(base64.b64decode(self.b64)))
            buf = io.BytesIO()
            im.convert("RGB").resize((rw, rh)).save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode(), rw, rh
        except Exception:
            return self.b64, self.width, self.height


# ---------------------------------------------------------- frame math
#
# Aspect-matched pointing resolution table and coordinate scaling ported
# from farzaa/clicky `leanring-buddy/ElementLocationDetector.swift` (MIT).
# Source: https://github.com/farzaa/clicky

POINTING_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (1024, 768),   # 4:3   = 1.333 (legacy displays)
    (1280, 800),   # 16:10 = 1.600 (MacBook Air/Pro, 16:10 panels)
    (1366, 768),   # ~16:9 = 1.779 (external monitors, ultrawide fallback)
)


def pick_pointing_resolution(width: int, height: int) -> tuple[int, int]:
    """Pick the pointing resolution from `POINTING_RESOLUTIONS` whose aspect
    ratio is closest to `(width, height)`, defaulting to (1280, 800)."""
    try:
        w = int(width)
        h = int(height)
    except (TypeError, ValueError):
        return (1280, 800)
    if w <= 0 or h <= 0:
        return (1280, 800)
    display_ratio = float(w) / float(max(1, h))
    best_w, best_h = 1280, 800
    smallest_diff = float("inf")
    for rw, rh in POINTING_RESOLUTIONS:
        ratio = float(rw) / float(rh)
        diff = abs(display_ratio - ratio)
        if diff < smallest_diff:
            smallest_diff = diff
            best_w, best_h = rw, rh
    return (best_w, best_h)


def scale_point_from_resolution(
    px: float,
    py: float,
    res_w: int,
    res_h: int,
    disp_w: int,
    disp_h: int,
    flip_y: bool = False,
) -> tuple[int, int]:
    """Clamp `(px, py)` to `[0..res_w, 0..res_h]`, scale into
    `[0..disp_w, 0..disp_h]`, optionally flip Y origin (bottom-left
    vs top-left), and clamp to display bounds.

    Mirrors `ElementLocationDetector.detectElementLocation` (lines 103-118)
    from farzaa/clicky (MIT).
    """
    rw = max(1.0, float(res_w))
    rh = max(1.0, float(res_h))
    dw = max(0.0, float(disp_w))
    dh = max(0.0, float(disp_h))

    clamped_x = max(0.0, min(float(px), rw))
    clamped_y = max(0.0, min(float(py), rh))

    scaled_x = (clamped_x / rw) * dw
    scaled_y = (clamped_y / rh) * dh
    if flip_y:
        scaled_y = dh - scaled_y

    scaled_x = max(0.0, min(scaled_x, dw))
    scaled_y = max(0.0, min(scaled_y, dh))
    return int(round(scaled_x)), int(round(scaled_y))


def _scale(m: dict) -> float:
    try:
        s = float(m.get("scale", 1) or 1)
    except (TypeError, ValueError):
        s = 1.0
    return s if s > 0 else 1.0


def convert(x: float, y: float, frame: str, mons: list,
            output: str | None = None) -> tuple:
    """Point in `frame` -> compositor-global logical (int, int)."""
    if frame in ("global", "logical"):
        return int(round(x)), int(round(y))
    mons = [m for m in (mons or []) if isinstance(m, dict)]
    from . import points
    if frame == "canvas":
        ox, oy, _, _ = points.logical_bbox(mons)
        return int(round(x + ox)), int(round(y + oy))
    if frame != "shot":
        raise ValueError(f"unknown frame {frame!r}")
    if not mons:
        return int(round(x)), int(round(y))
    one = next((m for m in mons if output and m.get("name") == output),
               None)
    if one is not None:
        s = _scale(one)
        return (int(round(one.get("x", 0) + x / s)),
                int(round(one.get("y", 0) + y / s)))
    # grim composites the whole layout at the highest output scale
    s = max(_scale(m) for m in mons)
    ox, oy, _, _ = points.logical_bbox(mons)
    return int(round(ox + x / s)), int(round(oy + y / s))


# ------------------------------------------------------------ settings

def _f(v, default: float) -> float:
    try:
        r = float(v)
        return r if math.isfinite(r) else default
    except (TypeError, ValueError):
        return default


def settings(cfg: dict | None) -> dict:
    gc = (cfg or {}).get("ground", {}) or {}
    health = (cfg or {}).get("health", {}) or {}
    brain = (cfg or {}).get("brain.uitars", {}) or {}
    url = (gc.get("uitars_url") or health.get("uitars")
           or brain.get("base_url") or "http://127.0.0.1:8081")
    url = str(url).rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    local = config.local_enabled(cfg)
    return {
        "providers": [p.strip() for p in str(
            gc.get("providers", "control,a11y,vlm,uitars,jev")).split(",")
            if p.strip() and (local or p.strip() != "uitars")],
        "min_conf": _f(gc.get("min_confidence"), 0.5),
        "budget": _f(gc.get("budget_ms"), 1200.0) / 1000.0,
        "fallback": _f(gc.get("fallback_timeout_ms"), 5000.0) / 1000.0,
        "uitars_url": url,
        "uitars_model": str(gc.get("uitars_model", "ui-tars")),
        "uitars_coords": str(gc.get("uitars_coords", "px")),
        "max_side": int(_f(gc.get("max_side"), 1280.0)),
        "a11y_frame": str(gc.get("a11y_frame", "global")),
    }


# ----------------------------------------------------------- transport

def _post_json(url: str, body: dict, timeout: float,
               headers: dict | None = None):
    """POST JSON, return the decoded body; None when it is not JSON;
    ProviderDown when the endpoint is unreachable."""
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ProviderDown(str(e)) from None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _is_loopback(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


# -------------------------------------------------------------- UI-TARS

_NUM = r"-?\d+(?:\.\d+)?"
_PAIR = re.compile(rf"\(\s*({_NUM})\s*,\s*({_NUM})\s*\)")
_BARE = re.compile(rf"(?<![\w.])({_NUM})\s*,\s*({_NUM})(?![\w.])")


def parse_uitars_text(text, size: tuple, coords: str = "px"):
    """UI-TARS reply -> (x, y) in the sent image's pixels, or None.
    Accepts `(x,y)`, `click(start_box='(x,y)')`, `<|box_start|>(x,y)
    <|box_end|>`, bare `x, y`. Floats <= 1 are relative; coords=rel1000
    means 0..1000. Anything out of bounds or non-finite is malformed."""
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        return None
    m = _PAIR.search(text) or _BARE.search(text)
    if not m:
        return None
    try:
        a, b = float(m.group(1)), float(m.group(2))
    except ValueError:
        return None
    if not (math.isfinite(a) and math.isfinite(b)):
        return None
    w, h = size
    if "." in m.group(1) + m.group(2):
        if not (0.0 <= a <= 1.0 and 0.0 <= b <= 1.0):
            return None
        a, b = a * w, b * h
    elif coords == "rel1000":
        a, b = a * w / 1000.0, b * h / 1000.0
    if a < 0 or b < 0 or a > w or b > h:
        return None
    return int(round(a)), int(round(b))


def _logprob_conf(choice: dict) -> float | None:
    try:
        toks = choice["logprobs"]["content"]
        lps = [float(t["logprob"]) for t in toks
               if isinstance(t, dict)
               and re.search(r"\d", str(t.get("token", "")))]
        lps = [v for v in lps if math.isfinite(v)]
        if lps:
            return max(0.0, min(1.0, math.exp(sum(lps) / len(lps))))
    except (KeyError, TypeError, ValueError):
        pass
    return None


_UITARS_PROMPT = ("Output only the coordinate of one point in your "
                  "response. What element matches the following task: ")


def _uitars(ctx) -> Candidate | None:
    st = ctx.st
    if not _is_loopback(st["uitars_url"]):
        raise Skip("uitars url is not loopback; screenshots stay local")
    b64, w, h = ctx.shot.scaled(st["max_side"])
    data = _post_json(
        st["uitars_url"] + "/v1/chat/completions",
        {"model": st["uitars_model"], "temperature": 0, "max_tokens": 48,
         "logprobs": True,
         "messages": [{"role": "user", "content": [
             {"type": "text", "text": _UITARS_PROMPT + ctx.target},
             {"type": "image_url",
              "image_url": {"url": "data:image/png;base64," + b64}}]}]},
        ctx.timeout)
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    xy = parse_uitars_text(text, (w, h), st["uitars_coords"])
    if xy is None:
        return None
    conf = _logprob_conf(choice)
    return Candidate(xy[0], xy[1], 0.8 if conf is None else conf,
                     "uitars", size=(w, h), label=ctx.target)


# ----------------------------------------------------------------- a11y

_NAME_KEYS = ("label", "title", "name", "description", "text", "value")
_FOCUS_KEYS = ("focused", "is_focused", "active", "is_active")


def _rect(v):
    """frame -> (x, y, w, h) floats or None."""
    try:
        if isinstance(v, dict):
            x, y = v["x"], v["y"]
            w = v["width"] if "width" in v else v["w"]
            h = v["height"] if "height" in v else v["h"]
        elif isinstance(v, (list, tuple)) and len(v) == 4:
            x, y, w, h = v
        else:
            return None
        r = tuple(float(n) for n in (x, y, w, h))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(n) for n in r) or r[2] <= 0 or r[3] <= 0:
        return None
    return r


def _contains(rect, x, y):
    r = _rect(rect)
    return r is not None and r[0] <= x < r[0] + r[2] \
        and r[1] <= y < r[1] + r[3]


def _focused_window(listing):
    wins = listing.get("windows") if isinstance(listing, dict) else None
    for w in wins if isinstance(wins, list) else []:
        if not isinstance(w, dict) or not any(w.get(k)
                                              for k in _FOCUS_KEYS):
            continue
        pid = w.get("pid")
        wid = w.get("window_id", w.get("id"))
        if isinstance(pid, int) and isinstance(wid, int):
            return w, pid, wid
    return None


def _a11y(ctx) -> Candidate | None:
    """Accessibility-tree path via cua `get_window_state`. The element
    schema is unverified against a live driver (docs/LINUX.md spike), so
    parsing is tolerant and anything unexpected yields None, which sends
    the chain on to the pixel providers."""
    cua = ctx.cua
    if cua is None or not cua.available():
        raise Skip("cua-driver not available")
    from . import cua as _cua
    try:
        fw = _focused_window(cua.list_windows(
            timeout=min(ctx.timeout, 0.5)))
        if fw is None:
            raise Skip("no focused window")
        win, pid, wid = fw
        tree = cua.window_state(pid, wid, timeout=max(ctx.timeout, 0.1))
    except _cua.CuaError as e:
        if e.cua_code in (_cua.DOWN, _cua.TIMEOUT):
            raise ProviderDown(str(e)) from None
        return None
    els = tree.get("elements") if isinstance(tree, dict) else None
    if not isinstance(els, list):
        return None
    want = ctx.target.strip().casefold()
    point = getattr(ctx, "point", None)
    best, score = [], 0.0
    for el in els:
        if not isinstance(el, dict):
            continue
        rect = _rect(el.get("frame", el.get("bounds")))
        names = [el[k].strip().casefold() for k in _NAME_KEYS
                 if isinstance(el.get(k), str) and el[k].strip()]
        if rect is None or (not names and point is None):
            continue
        if point is not None:
            role = str(el.get("role", "")).casefold().removeprefix("ax")
            if role in (
                    "window", "application", "document", "webarea",
                    "root", "desktop"):
                continue
            x, y, w, h = rect
            if ctx.st["a11y_frame"] == "window":
                wr = _rect(win.get("frame", win.get("bounds")))
                if wr is None:
                    continue
                x, y = x + wr[0], y + wr[1]
            rect = (x, y, w, h)
            label = names[0] if names else str(
                el.get("id") or el.get("role") or "")
            if label and _contains(rect, *point):
                best.append((rect, label))
            continue
        sc = 1.0 if want in names else (
            0.85 if any(want in n or n in want for n in names) else 0.0)
        if sc > score:
            best, score = [rect], sc
        elif sc == score and sc > 0:
            best.append(rect)
    if not best:
        return None
    if point is not None:
        rect, label = min(best, key=lambda item: item[0][2] * item[0][3])
        return Candidate(*point, 1.0, "a11y", frame="global",
                         label=label, window=str(win.get("title") or ""),
                         rect=rect)
    x, y, w, h = best[0]
    if ctx.st["a11y_frame"] == "window":
        wr = _rect(win.get("frame", win.get("bounds")))
        if wr is None:
            return None
        x, y = x + wr[0], y + wr[1]
    conf = score if len(set(best)) == 1 else 0.4   # ambiguous -> low
    return Candidate(x + w / 2.0, y + h / 2.0, conf, "a11y", frame="global",
                     label=ctx.target,
                     window=str(win.get("title") or win.get("name") or ""),
                     rect=(x, y, w, h))


# ------------------------------------------------- control channel (U3)

def _control(ctx) -> Candidate | None:
    """Per-app control channel (KTD3): the app's own widget registry —
    `ui.elements` id/label/rect — ahead of the vision providers when
    the focused app ships a channel (FilmCraft: `--control 9876`,
    registered in wisp/control.py).

    Channel rects are window-local points translated against the app's
    live compositor window bounds; a rect whose center can't be placed
    inside those bounds is dropped — the channel is unauthenticated
    loopback and a squatting process must not redirect a click outside
    the app's window. Dispatch stays on the standard cua pixel path.
    """
    from . import control as _ctl
    from . import trace as _trace
    win = _ctl.focused_window(cua=ctx.cua)
    if win is None:
        raise Skip("no focused window")
    ep = _ctl.AppControlRegistry(ctx.cfg).match(win)
    if ep is None:
        raise Skip("focused app has no control channel")
    st = _ctl.settings(ctx.cfg)
    try:
        with _ctl.ControlClient(
                ep.host, ep.port,
                connect_s=min(ctx.timeout, st["connect_s"]),
                read_s=max(0.3, min(ctx.timeout + 0.5,
                                    st["read_s"]))) as cli:
            els = cli.elements()
            try:
                insp = cli.inspect()
            except _ctl.ControlError:
                insp = {}      # elements alone still ground + snapshot
    except _ctl.ControlError as e:
        # absent channel degrades to the generic lane; a STALLED or
        # garbage one reports down so tried==down reads ground_down
        if e.code == "down":
            raise Skip(f"control channel unreachable: {e}") from None
        raise ProviderDown(f"control channel {e.code}") from None
    # match the target against element id/label, a11y-style scoring
    want = ctx.target.strip().casefold()
    point = getattr(ctx, "point", None)
    if point is not None and not _contains(win.get("bounds"), *point):
        # resolve_rect confines its CENTER for named grounding. A numeric
        # point must itself stay inside the focused app: an oversized
        # unauthenticated control rect cannot license another window.
        return None
    score = 0.0
    cands = []
    ppt = (insp.get("pixelsPerPoint") if isinstance(insp, dict)
           else None)
    for el in els:
        if point is not None:
            rect = _ctl.resolve_rect(el.get("rect"), win, ppt=ppt,
                                     slack=st["slack_px"])
            if _contains(rect, *point):
                cands.append(el)
            continue
        keys = [n.casefold() for n in (el.get("id"), el.get("label"))
                if n]
        if not keys:
            continue
        sc = 1.0 if want in keys else (
            0.85 if any(want in n or n in want for n in keys) else 0.0)
        if sc > score:
            cands, score = [el], sc
        elif sc == score and sc > 0:
            cands.append(el)
    # validate each top-scored rect against compositor bounds; the
    # first that lands inside the app's window grounds the click
    el = grect = None
    if point is not None:
        cands.sort(key=lambda item: item["rect"][2] * item["rect"][3])
    for cand_el in cands:
        grect = _ctl.resolve_rect(cand_el.get("rect"), win, ppt=ppt,
                                  slack=st["slack_px"])
        if grect is not None:
            el = cand_el
            break
    hit = {"id": el["id"], "label": el.get("label", ""),
           "rect": list(el["rect"])} if el is not None else None
    # the pre-dispatch snapshot for verify's control rung — recorded
    # whether or not the target matched (a miss still leaves usable
    # before-state for the diff)
    _ctl.note_before(_trace.current(), ep.app, insp, els, hit=hit,
                     cap=st["element_cap"])
    if el is None:
        return None
    cx, cy = point if point is not None else (
        grect[0] + grect[2] / 2.0, grect[1] + grect[3] / 2.0)
    conf = 1.0 if point is not None else (
        score if len(cands) == 1 else 0.4)    # ambiguous name -> low
    return Candidate(cx, cy, conf, "control", frame="global",
                     label=el.get("label") or el["id"],
                     window=win.get("title") or "", rect=grect)


# ------------------------------------------------- Jev (vision fallback)

def _prob(v) -> float:
    try:
        p = float(v)
    except (TypeError, ValueError):
        return 0.0
    return p if math.isfinite(p) and 0.0 <= p <= 1.0 else 0.0


def _jev_locate(screenshot_b64: str, target: str, region_hint: str,
                power: float, model: str | None, cfg: dict | None,
                timeout: float):
    """#77's engine: noul patch probabilities -> power-sharpened center
    of mass. Returns (x, y, max_probability) in screenshot px, or None.
    ProviderDown when the endpoint is unreachable."""
    deadline = time.monotonic() + max(0.0, _f(timeout, 0.0))
    if not _PIL_AVAILABLE:
        raise Skip("PIL not installed")
    try:
        raw_bytes = base64.b64decode(screenshot_b64)
        image = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        return None

    width, height = image.size
    hint = (region_hint or "").lower()

    # 1. Determine Region of Interest (ROI)
    if any(k in hint for k in ("menu", "bar", "top", "panel", "status")):
        y_min, y_max = 0, min(54, height)
    elif any(k in hint for k in ("dock", "bottom", "taskbar")):
        y_min, y_max = max(0, height - 70), height
    else:
        y_min, y_max = 0, height

    # 2. Extract candidate icon/element patches (36x36 with stride 18)
    patch_size = 36
    stride = 18
    candidates = []

    for y in range(y_min, max(y_min + 1, y_max - patch_size + 1), stride):
        for x in range(0, max(1, width - patch_size + 1), stride):
            box = (x, y, x + patch_size, y + patch_size)
            patch = image.crop(box)
            buf = io.BytesIO()
            patch.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            candidates.append({
                "x": x + patch_size // 2,
                "y": y + patch_size // 2,
                "b64": b64
            })

    if not candidates:
        return None

    # Cap to top candidate patches to stay within token / batch budgets
    max_patches = 40
    if len(candidates) > max_patches:
        # Uniform sampling across candidate range
        step = len(candidates) / max_patches
        candidates = [candidates[int(i * step)] for i in range(max_patches)]

    # 3. Formulate `noul` (Bernoulli) questions
    questions = {}
    for i, c in enumerate(candidates):
        questions[f"p_{i}"] = {
            "type": "noul",
            "instructions": f"Does this image crop clearly show the {target}?"
        }

    chosen_model = model or (cfg or {}).get("agent", {}).get(
        "model", "typesafe/jev-1.13")

    payload = {
        "model": chosen_model,
        "state": f"Ground UI element on desktop: {target}",
        "questions": questions
    }
    try:
        key = config.load_api_key()
    except Exception:
        key = ""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    data = _post_json(
        config.JEV_ENDPOINT, payload, remaining,
        {"Authorization": f"Bearer {key}",
         "HTTP-Referer": "https://github.com/duketopceo/wisp",
         "X-Title": "Wisp Grounding Agent"})
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        return None

    # 4. Extract calibrated probabilities
    probs = []
    coords = []
    for i, c in enumerate(candidates):
        a = answers.get(f"p_{i}")
        probs.append(_prob(a.get("noul", 0.0)) if isinstance(a, dict)
                     else 0.0)
        coords.append([c["x"], c["y"]])

    if not probs:
        return None

    max_p = max(probs)
    if max_p < 0.20:
        return None

    # 5. Power-Level Sharpening (P^α)
    # Raising probabilities to power α cools temperature, suppressing noise to zero
    powered = [p ** power for p in probs]
    sum_powered = sum(powered)

    if sum_powered <= 1e-9:
        best_idx = probs.index(max_p)
        return int(coords[best_idx][0]), int(coords[best_idx][1]), max_p

    # 6. Probabilistic Centering (Center of Mass Expectation E[X, Y])
    weights = [w / sum_powered for w in powered]
    center_x = sum(coords[i][0] * weights[i] for i in range(len(coords)))
    center_y = sum(coords[i][1] * weights[i] for i in range(len(coords)))

    return int(round(center_x)), int(round(center_y)), max_p


_VLM_POINT_PROMPT = (
    "Locate the UI element described as: {target}{hint}.\n"
    "The attached screenshot is {rw}x{rh} pixels (origin 0,0 at top-left).\n"
    "Reply with ONLY a single point tag `[POINT:x,y:{target}]` "
    "at the exact center of the element, or `NONE` if it is not visible "
    "or the target is ambiguous. Do not add bare coordinates or prose."
)


def _vlm_locate(shot: Shot, target: str, region_hint: str = "",
                cfg: dict | None = None,
                timeout: float = 5.0) -> Tuple[int, int, float] | None:
    """Single-shot aspect-matched VLM pointing (HeyClicky parity).
    Resizes `shot` to `pick_pointing_resolution`, asks `brain.chat` for a
    single target-labelled `[POINT:x,y:label]`, and scales back to `shot`
    pixels via `scale_point_from_resolution`. Legacy bare coordinates are
    retained only as unsupported, zero-confidence predictions."""
    from . import brain, points as _points
    deadline = time.monotonic() + max(0.0, _f(timeout, 5.0))
    b64, rw, rh = shot.resized_pointing()
    hint_str = f" (region hint: {region_hint})" if region_hint else ""
    prompt = _VLM_POINT_PROMPT.format(
        target=target, hint=hint_str, rw=rw, rh=rh)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ],
    }]
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        res = brain.chat(messages, cfg or {}, timeout=remaining)
        text = str((res or {}).get("content") or "").strip()
    except Exception as e:
        raise ProviderDown(str(e)) from None
    if not text or text.upper() == "NONE":
        return None
    _, marks = _points.extract(text)
    # Bounds alone are not target support. Bare coordinates, conflicting
    # marks/labels and hedged prose remain untrusted predictions; only a
    # single explicit mark naming the requested target gets the supported
    # response score. This is not calibrated correctness or element proof:
    # the executor still independently requires observed element evidence.
    supported = (len(marks) == 1
                 and re.fullmatch(r"\[POINT:[^\[\]]+\]", text) is not None
                 and " ".join(str(marks[0].get("label", "")).casefold().split())
                 == " ".join(target.casefold().split()))
    px_py = None
    if marks:
        px_py = (float(marks[0]["x"]), float(marks[0]["y"]))
    else:
        xy = parse_uitars_text(text, (rw, rh), "px")
        if xy is not None:
            px_py = (float(xy[0]), float(xy[1]))
    if px_py is None:
        return None
    if px_py[0] < 0 or px_py[1] < 0 or px_py[0] > rw or px_py[1] > rh:
        return None
    sx, sy = scale_point_from_resolution(
        px_py[0], px_py[1], rw, rh, shot.width, shot.height)
    return sx, sy, 0.85 if supported else 0.0


def _vlm(ctx) -> Candidate | None:
    hint = ctx.region_hint or (
        "menu bar" if any(w in ctx.target.lower()
                          for w in ("menu", "bar", "top", "panel")) else "")
    r = _vlm_locate(ctx.shot, ctx.target, hint, ctx.cfg, ctx.timeout)
    if r is None:
        return None
    return Candidate(r[0], r[1], r[2], "vlm",
                     size=(ctx.shot.width, ctx.shot.height),
                     label=ctx.target)


def _jev(ctx) -> Candidate | None:
    deadline = time.monotonic() + max(0.0, _f(ctx.timeout, 0.0))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    hint = ctx.region_hint or (
        "menu bar" if any(w in ctx.target.lower()
                          for w in ("menu", "bar", "top", "panel")) else "")
    gc = (ctx.cfg or {}).get("ground", {}) or {}
    best_low = None
    # Older explicit "jev"-only chains retain their VLM-first fallback.
    # An explicit vlm provider owns that attempt in a modern chain; never
    # make the same vision request again from the patch provider.
    if "vlm" not in ctx.st["providers"] and gc.get("jev_patches") != "true":
        try:
            vr = _vlm_locate(ctx.shot, ctx.target, hint, ctx.cfg, remaining)
        except ProviderDown:
            vr = None
        if time.monotonic() >= deadline:
            return None
        if vr is not None:
            best_low = Candidate(vr[0], vr[1], vr[2], "vlm",
                                 size=(ctx.shot.width, ctx.shot.height),
                                 label=ctx.target)
            if best_low.confidence >= ctx.st["min_conf"]:
                return best_low
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    r = _jev_locate(ctx.shot.b64, ctx.target, hint, 6.0, None, ctx.cfg,
                    remaining)
    if r is None:
        return best_low
    if best_low is not None and best_low.confidence > r[2]:
        return best_low
    return Candidate(r[0], r[1], r[2], "jev",
                     size=(ctx.shot.width, ctx.shot.height),
                     label=ctx.target)


def ground_element(
    screenshot_b64: str,
    target_description: str,
    region_hint: str = "menu bar",
    power: float = 6.0,
    model: str | None = None,
    cfg: dict | None = None
) -> Tuple[int, int] | None:
    """Legacy #77 entry point: (x, y) in screenshot px or None. Kept for
    callers that want the raw Jev engine; the act loop uses
    `ground_target`."""
    try:
        r = _jev_locate(screenshot_b64, target_description, region_hint,
                        power, model, cfg, 20)
    except (ProviderDown, Skip):
        return None
    return (r[0], r[1]) if r else None


# ---------------------------------------------------------------- chain

PROVIDERS = {
    "control": {"fn": _control, "fast": True},
    "a11y": {"fn": _a11y, "fast": True},
    "uitars": {"fn": _uitars, "fast": True},
    "vlm": {"fn": _vlm, "fast": False},
    "jev": {"fn": _jev, "fast": False},
}


class _Ctx:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def target_at_point(x: int, y: int, cfg: dict | None = None) -> Target | None:
    """Read-only element hit test in global logical coordinates.

    This is evidence, not another model prediction. A named VLM/label or
    numeric model point can use the same live control/a11y element.
    """
    from . import cancel
    cfg = cfg or {}
    st = settings(cfg)
    try:
        cua = _default_cua()
    except Exception:
        cua = None
    ctx = _Ctx(target="", point=(x, y), cfg=cfg, st=st,
               timeout=st["budget"], cua=cua)
    for provider in (_control, _a11y):
        cancel.check()
        try:
            c = provider(ctx)
        except cancel.Cancelled:
            raise
        except Exception:
            continue
        if c is not None and _contains(c.rect, x, y) \
                and c.confidence >= st["min_conf"]:
            return Target(x, y, "global", c.confidence, c.source,
                          c.label, c.window, c.rect)
    return None


def _default_capture():
    from . import pipeline
    out = pipeline.capture_screen()
    if not out or not out.exists():
        return None
    try:
        return Shot.from_bytes(out.read_bytes())
    finally:
        out.unlink(missing_ok=True)


def _default_cua():
    from . import cua
    return cua.Cua()


def _in_bounds(c: Candidate, shot: Shot) -> bool:
    if not (math.isfinite(c.x) and math.isfinite(c.y)):
        return False
    if c.frame != "shot":
        return True
    w, h = c.size or (shot.width, shot.height)
    return 0 <= c.x <= w and 0 <= c.y <= h


def _attempt(shot: Shot, target: str, cfg: dict, st: dict, providers: dict,
             cua, clock, region_hint: str):
    """One pass over the chain. Returns (best, tried, down): `best` is
    the first candidate at/above min confidence, else the strongest
    below it (or None)."""
    deadline = clock() + st["budget"]
    best_low = None
    tried = down = 0
    for name in st["providers"]:
        spec = providers.get(name)
        if not spec:
            continue
        if spec.get("fast", True):
            remaining = deadline - clock()
            if remaining <= 0.02:
                continue                     # P7 budget spent: skip
            timeout = min(remaining, st["budget"])
        else:
            timeout = st["fallback"]         # slow fallback, own budget
        ctx = _Ctx(target=target, region_hint=region_hint, shot=shot,
                   cfg=cfg, st=st, timeout=timeout, cua=cua)
        try:
            c = spec["fn"](ctx)
            tried += 1
        except Skip:
            continue
        except ProviderDown:
            tried += 1
            down += 1
            continue
        except Exception:
            tried += 1
            continue
        if c is None or not _in_bounds(c, shot):
            continue
        conf = c.confidence if math.isfinite(c.confidence) else 0.0
        c.confidence = max(0.0, min(1.0, conf))
        if c.confidence >= st["min_conf"]:
            return c, tried, down
        if best_low is None or c.confidence > best_low.confidence:
            best_low = c
    return best_low, tried, down


def ground_target(target: str, cfg: dict | None = None, *, capture=None,
                  monitors=None, providers=None, cua=None,
                  clock=time.monotonic, region_hint: str = "",
                  output: str | None = None) -> Target:
    """Name -> compositor-global Target, or GroundRefused.

    One re-observe on a missing/low-confidence result (fresh capture,
    full chain); never a second. Cancellation (`cancel.Cancelled`)
    propagates."""
    from . import cancel, points
    cfg = cfg or {}
    name = (target or "").strip()
    if not name:
        raise GroundRefused("ground_failed", "empty", "no target given")
    st = settings(cfg)
    use_default = providers is None
    providers = PROVIDERS if use_default else providers
    capture = capture or _default_capture
    if cua is None and use_default and "a11y" in st["providers"]:
        try:
            cua = _default_cua()
        except Exception:
            cua = None
    if output is None:
        output = (cfg.get("screen", {}) or {}).get("output") or None
    best = None
    tried = down = 0
    for _attempt_no in (1, 2):
        cancel.check()
        shot = capture()
        if shot is None:
            raise GroundRefused("ground_failed", "no_capture",
                                "could not capture the screen")
        best, t, d = _attempt(shot, name, cfg, st, providers, cua, clock,
                              region_hint)
        tried, down = tried + t, down + d
        if best is not None and best.confidence >= st["min_conf"]:
            mons = monitors if monitors is not None else points.monitors()
            x, y = best.x, best.y
            if best.frame == "shot":
                w, h = best.size or (shot.width, shot.height)
                x, y = x * shot.width / w, y * shot.height / h
            gx, gy = convert(x, y, best.frame, mons, output)
            from . import trace as _trace
            _trace.emit(_trace.current(), "ground", "act",
                        {"target": name, "src": best.source,
                         "conf": round(best.confidence, 3),
                         "x": gx, "y": gy, "tried": tried,
                         "down": down})
            # an element rect the a11y lane resolved rides along so the
            # verify ladder can crop its masked diff to the real bounds
            # instead of a point box (shot-frame rects stay None)
            rect = best.rect if best.frame in ("global", "logical") \
                else None
            return Target(gx, gy, "global", round(best.confidence, 3),
                          best.source, best.label or name, best.window,
                          rect)
    from . import trace as _trace
    _trace.emit(_trace.current(), "ground_refused", "act",
                {"target": name, "tried": tried, "down": down,
                 "best": (f"{best.source} {best.confidence:.2f}"
                          if best is not None else None)})
    if best is not None:
        raise GroundRefused("ground_failed", "low_confidence",
                            f"{best.source} {best.confidence:.2f} < "
                            f"{st['min_conf']:.2f}")
    if tried and tried == down:
        raise GroundRefused("ground_down", "all_down",
                            "no grounding provider reachable")
    raise GroundRefused("ground_failed", "not_found", name)


# --------------------------------------------------------------- events

def emit_target(state, phase: str | None, target: Target | None = None,
                *, window: str = "", label: str = "",
                delivery: str = "") -> None:
    """W21 `cua.target` event (compositor-global px). phase None clears
    (`x`/`y` null). `delivery` (U5) names the channel the aim would /
    did use so the overlay can show when it escalates to the real
    pointer. Never raises; a state without emit_event is a no-op."""
    fn = getattr(state, "emit_event", None)
    if not callable(fn):
        return
    try:
        if target is None or phase is None:
            fn("cua.target", x=None, y=None)
            return
        fn("cua.target", x=target.x, y=target.y,
           window=window or target.window or "",
           label=label or target.label or "",
           confidence=target.confidence, phase=phase,
           delivery=delivery)
    except Exception:
        pass
