#!/usr/bin/env python3
"""Grounding model bake-off (U8): which pointing model is right most often,
and at what cost per case.

    python scripts/grounding_bakeoff.py --list-cases
    python scripts/grounding_bakeoff.py --fake                  # offline
    OPENROUTER_API_KEY=... python scripts/grounding_bakeoff.py \
        --live --cap 0.80 --models qwen/qwen3-vl-8b-instruct,...

Cases are synthetic screens drawn here with PIL (no real screenshots, no
personal data), deterministic from `CONTENT_SEED` and the case id. The
pool is split once, from `--seed`, into a tuning set and a held-out set;
the two never overlap and only the held-out set is scored. Each case is
sent the way production sends it (`Shot.letterboxed`, the same prompt as
`grounding._vlm_locate`) and the reply is parsed by
`grounding.parse_vlm_reply`, so a conversion bug shows up as a miss.

A run has a hard spend cap. It stops before the call that could cross it,
prints the table so far (with n per row) and exits 3. Synthetic cases are
a weak signal: flat, high-contrast, English labels, no real app chrome.
Treat a ranking as a screen for candidates, not as a measured default.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import functools
import hashlib
import io
import json
import os
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from wisp import grounding  # noqa: E402

CONTENT_SEED = 8_0042          # case content; independent of the split seed
POOL = 120                     # cases drawn in total
HELD_OUT_SHARE = 0.4           # share of the pool held out, by hash
# Source canvases (w, h): 16:9, 16:10, 4:3, ultrawide, two portraits. The
# last four force a letterbox pad against the three pointing resolutions.
CANVASES = ((1920, 1080), (1440, 900), (1600, 1200), (2560, 1080),
            (1080, 1920), (1200, 1600))
LABELS = ("Save", "Cancel", "Export", "Settings", "Share", "Print",
          "Undo", "Redo", "Upload", "Archive", "Rename", "Delete",
          "Refresh", "Search", "Filter", "Sort", "Invite", "Publish")
MODES = ("direct", "labels")   # labels: prompt also lists visible labels
# Per-call reserve before any cost is observed: bounds the first call's
# overshoot. Measured in the pilot call, see docs/ACCURACY.md.
FIRST_CALL_RESERVE_USD = 0.01
MAX_TOKENS = 64
CHAT = "https://openrouter.ai/api/v1/chat/completions"


# ------------------------------------------------------------- cases

@dataclasses.dataclass(frozen=True)
class Case:
    cid: int
    width: int
    height: int
    target: str
    rect: tuple            # (x0, y0, x1, y1) source pixels, the target's
    labels: tuple          # every label drawn, in draw order
    rects: tuple = ()      # every button rect, same order as labels

    @property
    def center(self) -> tuple:
        return ((self.rect[0] + self.rect[2]) / 2,
                (self.rect[1] + self.rect[3]) / 2)

    def hit(self, x: float, y: float) -> bool:
        return self.rect[0] <= x <= self.rect[2] \
            and self.rect[1] <= y <= self.rect[3]


def _bucket(seed: int, cid: int) -> float:
    h = hashlib.sha256(f"{seed}:{cid}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def split(seed: int, pool: int = POOL,
          share: float = HELD_OUT_SHARE) -> tuple[list, list]:
    """(tuning ids, held-out ids): a partition of range(pool), the
    held-out ids picked by hash of (seed, id). Same seed, same split;
    the sets cannot overlap."""
    held = sorted(i for i in range(pool) if _bucket(seed, i) < share)
    hs = set(held)
    return [i for i in range(pool) if i not in hs], held


def make_case(cid: int) -> Case:
    rnd = random.Random(f"{CONTENT_SEED}:{cid}")
    w, h = CANVASES[cid % len(CANVASES)]
    n = rnd.randint(6, 10)
    labels = tuple(rnd.sample(LABELS, n))
    cols = 3 if w < h else 4
    rows = -(-n // cols)
    bw, bh = int(w * 0.17), int(min(w, h) * 0.07)
    gx, gy = (w - cols * bw) // (cols + 1), (h - 90 - rows * bh) // (rows + 1)
    rects = []
    for i in range(n):
        r, c = divmod(i, cols)
        x0 = gx + c * (bw + gx) + rnd.randint(-gx // 4, gx // 4)
        y0 = 90 + gy + r * (bh + gy) + rnd.randint(-gy // 4, gy // 4)
        rects.append((x0, y0, x0 + bw, y0 + bh))
    t = rnd.randrange(n)
    return Case(cid, w, h, labels[t], rects[t], labels, tuple(rects))


def _font(size: int):
    for path in ("/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


@functools.lru_cache(maxsize=64)
def render(case: Case) -> bytes:
    """PNG of the synthetic screen for `case`."""
    rnd = random.Random(f"{CONTENT_SEED}:paint:{case.cid}")
    bg = tuple(rnd.randint(225, 245) for _ in range(3))
    im = Image.new("RGB", (case.width, case.height), bg)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, case.width, 60), fill=(45, 52, 70))
    d.text((24, 14), "Project Dashboard", fill=(255, 255, 255),
           font=_font(30))
    fill = (rnd.randint(40, 90), rnd.randint(90, 140), rnd.randint(170, 230))
    size = max(18, int(min(case.width, case.height) * 0.028))
    for label, rect in zip(case.labels, case.rects):
        d.rounded_rectangle(rect, radius=10, fill=fill)
        d.text(((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2), label,
               fill=(255, 255, 255), font=_font(size), anchor="mm")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ----------------------------------------------------------- prompts

def build_prompt(case: Case, box: "grounding.Letterbox", mode: str) -> str:
    p = grounding._VLM_POINT_PROMPT.format(
        target=case.target, hint="", rw=box.width, rh=box.height)
    if box.padded:
        p += " Black bars at the edges are padding, not part of the screen."
    if mode == "labels":
        p += (" Accessibility labels of the visible controls: "
              + ", ".join(sorted(case.labels)) + ".")
    return p


# ---------------------------------------------------------- providers

@dataclasses.dataclass
class Reply:
    text: str
    cost_usd: float = 0.0


class SpendCapReached(Exception):
    pass


class FakeProvider:
    """Right on `right` of every 10 cases (by case id), exactly on the
    target in the SENT image's coordinates; otherwise points at the
    opposite corner. Never touches the network."""

    def __init__(self, name: str, right: int, cost_usd: float = 0.0001):
        self.name, self.right, self.cost = name, right, cost_usd

    def ask(self, case, box, png_b64, prompt, mode) -> Reply:
        if case.cid % 10 < self.right:
            cx, cy = case.center
            x = cx * box.scale_x + box.pad_x
            y = cy * box.scale_y + box.pad_y
        else:
            x, y = 1.0, 1.0
        return Reply(f"[POINT:{round(x)},{round(y)}:{case.target}]",
                     self.cost)


class OpenRouterProvider:
    """Live provider through OpenRouter chat completions. The key comes
    from the environment and is never printed or logged."""

    def __init__(self, model: str, key: str, timeout: float = 60.0):
        self.name, self._key, self.timeout = model, key, timeout

    def ask(self, case, box, png_b64, prompt, mode) -> Reply:
        body = json.dumps({
            "model": self.name, "temperature": 0, "max_tokens": MAX_TOKENS,
            "usage": {"include": True},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + png_b64}}]}],
        }).encode()
        req = urllib.request.Request(CHAT, data=body, headers={
            "Authorization": "Bearer " + self._key,
            "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                doc = json.load(r)
        except (urllib.error.URLError, OSError, ValueError):
            return Reply("", 0.0)       # counted as a miss, cost unknown
        text = ((doc.get("choices") or [{}])[0].get("message") or {}
                ).get("content") or ""
        cost = float((doc.get("usage") or {}).get("cost") or 0.0)
        return Reply(str(text).strip(), cost)


# ------------------------------------------------------------- scoring

def score(case: Case, box, reply_text: str) -> dict:
    """{hit, err_px}: the parsed point in source pixels against the
    target rect. No point (None, padding, off-image) is a miss."""
    r = grounding.parse_vlm_reply(reply_text, box, case.target) \
        if reply_text and reply_text.upper() != "NONE" else None
    if r is None:
        return {"hit": False, "err_px": None}
    cx, cy = case.center
    return {"hit": case.hit(r[0], r[1]),
            "err_px": round(((r[0] - cx) ** 2 + (r[1] - cy) ** 2) ** .5, 1)}


def table(rows: dict) -> list:
    """Rank rows {(model, mode): {n, hits, cost}} best accuracy first,
    ties broken by lower cost per case."""
    out = []
    for (model, mode), r in rows.items():
        n = r["n"]
        out.append({"model": model, "mode": mode, "n": n,
                    "hits": r["hits"],
                    "accuracy": round(r["hits"] / n, 3) if n else None,
                    "cost_total_usd": round(r["cost"], 6),
                    "cost_per_case_usd": round(r["cost"] / n, 6)
                    if n else None})
    out.sort(key=lambda x: (-(x["accuracy"] or 0),
                            x["cost_per_case_usd"] or 0))
    return out


def run(cases, providers, modes=MODES, cap_usd: float = 0.80,
        on_call=None) -> dict:
    """Case-major loop so a partial run stays balanced across rows.
    Stops BEFORE a call whose worst-case cost could cross `cap_usd`
    (the largest cost seen so far, or FIRST_CALL_RESERVE_USD before any)
    and returns what it has with `stopped=True`."""
    rows = {(p.name, m): {"n": 0, "hits": 0, "cost": 0.0}
            for p in providers for m in modes}
    spent, biggest, stopped = 0.0, 0.0, False
    for case in cases:
        shot = grounding.Shot.from_bytes(render(case))
        box = shot.letterboxed()
        for p in providers:
            for m in modes:
                if spent + (biggest or FIRST_CALL_RESERVE_USD) > cap_usd:
                    stopped = True
                    break
                prompt = build_prompt(case, box, m)
                rep = p.ask(case, box, box.b64, prompt, m)
                s = score(case, box, rep.text)
                row = rows[(p.name, m)]
                row["n"] += 1
                row["hits"] += int(s["hit"])
                row["cost"] += rep.cost_usd
                spent += rep.cost_usd
                biggest = max(biggest, rep.cost_usd)
                if on_call:
                    on_call(case, p.name, m, s, rep)
            if stopped:
                break
        if stopped:
            break
    return {"rows": table(rows), "spent_usd": round(spent, 6),
            "cap_usd": cap_usd, "stopped": stopped}


def render_table(res: dict) -> str:
    lines = [f"{'model':<44}{'mode':<8}{'n':>4}{'acc':>7}"
             f"{'$/case':>11}{'total $':>10}"]
    for r in res["rows"]:
        acc = "-" if r["accuracy"] is None else f"{r['accuracy']:.2f}"
        pc = "-" if r["cost_per_case_usd"] is None \
            else f"{r['cost_per_case_usd']:.6f}"
        lines.append(f"{r['model']:<44}{r['mode']:<8}{r['n']:>4}{acc:>7}"
                     f"{pc:>11}{r['cost_total_usd']:>10.4f}")
    tail = f"spent ${res['spent_usd']:.4f} of cap ${res['cap_usd']:.2f}"
    if res["stopped"]:
        tail += "  -- STOPPED AT THE CAP, partial table"
    return "\n".join(lines + [tail])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=20261105,
                    help="split seed (default: the dated one in the docs)")
    ap.add_argument("--cases", type=int, default=24,
                    help="held-out cases to score (default 24)")
    ap.add_argument("--models", default="")
    ap.add_argument("--cap", type=float, default=0.80, help="USD hard cap")
    ap.add_argument("--live", action="store_true",
                    help="call OpenRouter (needs OPENROUTER_API_KEY)")
    ap.add_argument("--fake", action="store_true", help="offline fakes")
    ap.add_argument("--list-cases", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    tuning, held = split(a.seed)
    held = held[:a.cases]
    if a.list_cases:
        print(json.dumps({"seed": a.seed, "held_out": held,
                          "tuning": tuning}))
        return 0
    if a.live == a.fake:
        print("choose exactly one of --live or --fake", file=sys.stderr)
        return 2
    if a.live:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            print("OPENROUTER_API_KEY is empty; not running",
                  file=sys.stderr)
            return 2
        models = [m for m in a.models.split(",") if m]
        if not models:
            print("--models is required with --live", file=sys.stderr)
            return 2
        providers = [OpenRouterProvider(m, key) for m in models]
    else:
        providers = [FakeProvider("fake/good", 8),
                     FakeProvider("fake/poor", 5)]
    t0 = time.monotonic()
    res = run([make_case(i) for i in held], providers, cap_usd=a.cap)
    res["seed"], res["held_out_ids"] = a.seed, held
    res["wall_s"] = round(time.monotonic() - t0, 1)
    print(json.dumps(res, indent=2) if a.json else render_table(res))
    return 3 if res["stopped"] else 0


if __name__ == "__main__":
    sys.exit(main())
