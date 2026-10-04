"""
Decision-Agent UI Grounding Engine (noul + Power-Leveling + Probabilistic Centering)
=====================================================================================
Replaces brittle chat LLM coordinate hallucination with calibrated System One
decision evaluations (Cloudflare Clef / Jev), power-temperature cooling, and
expected center-of-mass convergence.
"""
from __future__ import annotations

import base64
import io
import json
import urllib.request
import urllib.error
from typing import Optional, Tuple, List, Dict, Any

from . import config

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


def ground_element(
    screenshot_b64: str,
    target_description: str,
    region_hint: str = "menu bar",
    power: float = 6.0,
    model: str | None = None,
    cfg: dict | None = None
) -> Tuple[int, int] | None:
    """
    Locate the exact pixel center of an on-screen UI target (icon, button, menu item)
    using Clef/Jev `noul` evaluations, power-level sharpening, and probabilistic centering.

    Args:
        screenshot_b64: Base64-encoded PNG desktop screenshot
        target_description: Natural language target (e.g. "monitor icon", "mute button")
        region_hint: Region hint (e.g. "menu bar", "status bar", "dock", "top", "window")
        power: Exponent for probability sharpening (default 6.0)
        model: Decision model (defaults to configured agent model or cloudflare/clef-flash)
        cfg: Wisp config dict
    """
    if not _PIL_AVAILABLE:
        return None

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
            "instructions": f"Does this image crop clearly show the {target_description}?"
        }

    chosen_model = model or (cfg or {}).get("agent", {}).get("model", "typesafe/jev-1.13")

    payload = {
        "model": chosen_model,
        "state": f"Ground UI element on desktop: {target_description}",
        "questions": questions
    }

    try:
        req = urllib.request.Request(
            config.JEV_ENDPOINT,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {config.load_api_key()}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/duketopceo/wisp",
                "X-Title": "Wisp Grounding Agent",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            answers = data.get("answers", {})
    except Exception:
        return None

    # 4. Extract calibrated probabilities
    probs = []
    coords = []
    for i, c in enumerate(candidates):
        p = float(answers.get(f"p_{i}", {}).get("noul", 0.0))
        probs.append(p)
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
        return int(coords[best_idx][0]), int(coords[best_idx][1])

    # 6. Probabilistic Centering (Center of Mass Expectation E[X, Y])
    weights = [w / sum_powered for w in powered]
    center_x = sum(coords[i][0] * weights[i] for i in range(len(coords)))
    center_y = sum(coords[i][1] * weights[i] for i in range(len(coords)))

    return int(round(center_x)), int(round(center_y))
