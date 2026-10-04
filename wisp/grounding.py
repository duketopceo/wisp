"""
UI grounding adapter (W13, backend U12): target name -> screen point.

Extends the Decision-Agent grounding engine (#77: Clef/Jev `noul`
probabilistic centering, kept below as the vision-LLM fallback) into a
provider chain with one typed result:

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


@dataclasses.dataclass(frozen=True)
class Target:
    x: int
    y: int
    frame: str
    confidence: float
    source: str
    label: str = ""
    window: str = ""


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


# ---------------------------------------------------------- frame math

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
    return {
        "providers": [p.strip() for p in str(
            gc.get("providers", "a11y,uitars,jev")).split(",")
            if p.strip()],
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
    best, score = [], 0.0
    for el in els:
        if not isinstance(el, dict):
            continue
        rect = _rect(el.get("frame", el.get("bounds")))
        names = [el[k].strip().casefold() for k in _NAME_KEYS
                 if isinstance(el.get(k), str) and el[k].strip()]
        if rect is None or not names:
            continue
        sc = 1.0 if want in names else (
            0.85 if any(want in n or n in want for n in names) else 0.0)
        if sc > score:
            best, score = [rect], sc
        elif sc == score and sc > 0:
            best.append(rect)
    if not best:
        return None
    x, y, w, h = best[0]
    if ctx.st["a11y_frame"] == "window":
        wr = _rect(win.get("frame", win.get("bounds")))
        if wr is None:
            return None
        x, y = x + wr[0], y + wr[1]
    conf = score if len(set(best)) == 1 else 0.4   # ambiguous -> low
    return Candidate(x + w / 2.0, y + h / 2.0, conf, "a11y", frame="global",
                     label=ctx.target,
                     window=str(win.get("title") or win.get("name") or ""))


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
    data = _post_json(
        config.JEV_ENDPOINT, payload, timeout,
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


def _jev(ctx) -> Candidate | None:
    hint = ctx.region_hint or (
        "menu bar" if any(w in ctx.target.lower()
                          for w in ("menu", "bar", "top", "panel")) else "")
    r = _jev_locate(ctx.shot.b64, ctx.target, hint, 6.0, None, ctx.cfg,
                    ctx.timeout)
    if r is None:
        return None
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
    "a11y": {"fn": _a11y, "fast": True},
    "uitars": {"fn": _uitars, "fast": True},
    "jev": {"fn": _jev, "fast": False},
}


class _Ctx:
    def __init__(self, **kw):
        self.__dict__.update(kw)


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
            return Target(gx, gy, "global", round(best.confidence, 3),
                          best.source, best.label or name, best.window)
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
                *, window: str = "", label: str = "") -> None:
    """W21 `cua.target` event (compositor-global px). phase None clears
    (`x`/`y` null). Never raises; a state without emit_event is a no-op."""
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
           confidence=target.confidence, phase=phase)
    except Exception:
        pass
