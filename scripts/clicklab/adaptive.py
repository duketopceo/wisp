#!/usr/bin/env python3
"""adaptive.py — failure-bucket-driven task synthesis for clicklab (U7).

The loop this feeds is "run → verdict → see what's off → run THAT":
after each task the judge verdict lands in the rolling failure buckets
(wisp/train.py `compute_buckets`), and when a bucket clusters — say
model failures on scroll tasks — `pick_task` synthesizes the NEXT task
from a deterministic template pool for that skill. No generative model
involved: parameterized templates over known lab elements are cheaper
and debuggable. Buckets with no template pool (or a page the pools
don't know) fall back to suite tasks exercising the same skill, then
to plain suite order.

Every pool template emits (task, check, oracle_len) — the same triple
suites.json rows carry, so run.py treats synthesized and authored tasks
identically.
"""
import random
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from wisp import train  # noqa: E402

# the pools only know the core lab page — apps.html tasks fall back to
# same-skill suite picks instead of aiming at elements that don't exist
POOL_PAGE = "index.html"
# a bucket cell must reach this count before it steers synthesis
MIN_CLUSTER = 2

_BUTTONS = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT"]
_SHAPES = [("red circle", "shape-red-circle"),
           ("blue square", "shape-blue-square"),
           ("green triangle", "shape-green-triangle")]
_ORDINALS = ["first", "second", "third"]
_OPTIONS = ["alpha", "beta", "gamma"]
_WORDS = ["wisp", "arena", "hello", "note", "draft", "log", "task"]


def _t_click(rng) -> tuple:
    kind = rng.choice(("btn", "dot", "shape", "chk"))
    if kind == "btn":
        b = rng.choice(_BUTTONS)
        return (f"click the button labeled {b}",
                f"return s.counts['btn-{b.lower()}'] >= 1", 1)
    if kind == "dot":
        n = rng.randint(1, 8)
        return (f"click dot {n}", f"return s.counts['dot-{n}'] >= 1", 1)
    if kind == "shape":
        label, eid = rng.choice(_SHAPES)
        return (f"click the {label}",
                f"return s.counts['{eid}'] >= 1", 1)
    n = rng.randint(1, 3)
    return (f"click the {_ORDINALS[n - 1]} checkbox",
            f"return s.counts['chk-{n}'] >= 1", 1)


def _t_scroll(rng) -> tuple:
    # the "scroll then click misses by offset" bucket gets drilled here
    b = rng.choice(_BUTTONS)
    return rng.choice([
        ("scroll the list to the bottom", "return s.scroll_top > 400", 1),
        ("scroll the list down partway — stop around the middle",
         "return s.scroll_top > 300", 1),
        (f"scroll the list to the bottom then click {b}",
         f"return s.scroll_top > 400 && s.counts['btn-{b.lower()}'] >= 1",
         2),
    ])


def _t_type(rng) -> tuple:
    w = rng.choice(_WORDS)
    label, eid = rng.choice((("text field", "textin"),
                            ("big text area", "textbox")))
    return (f"type '{w}' into the {label}",
            f"return (s.typed['{eid}']||'').includes('{w}')", 2)


def _t_fill(rng) -> tuple:
    o = rng.choice(_OPTIONS)
    return (f"select '{o}' in the dropdown",
            "return s.events.some(e => e.id==='sel' && "
            f"e.value==='{o}')", 3)


POOLS = {"click": _t_click, "scroll": _t_scroll, "type": _t_type,
         "fill": _t_fill}
# skills the pools cover under another skill's exercises
POOL_ALIAS = {"select": "fill", "key": "type", "open": "click",
              "drag": "click"}


def _hot_cell(buckets: dict, min_cluster: int = MIN_CLUSTER) -> str:
    """The 'class|skill|surface' cell failing most — '' below the
    cluster floor so single flakes don't steer the curriculum."""
    cells = (buckets or {}).get("cells") or {}
    if not cells:
        return ""
    cell, n = max(cells.items(), key=lambda kv: (kv[1], kv[0]))
    return cell if n >= min_cluster else ""


def pick_task(buckets: dict, suite: list, rng: random.Random,
              page: str = POOL_PAGE, seen: set | None = None,
              min_cluster: int = MIN_CLUSTER) -> tuple | None:
    """Pick the next task: hottest failure bucket's skill → a pool
    template (lab page only) or a same-skill suite task → otherwise the
    next unseen suite row. Returns (task, check, oracle_len, meta)."""
    seen = seen if seen is not None else set()
    cell = _hot_cell(buckets, min_cluster)
    cls, skill = ("", "")
    if cell:
        parts = cell.split("|")
        cls, skill = parts[0], parts[1] if len(parts) > 1 else ""
    meta = {"bucket": cell or None, "class": cls or None,
            "skill": skill or None}
    if skill and page == POOL_PAGE:
        gen = POOLS.get(skill) or POOLS.get(POOL_ALIAS.get(skill, ""))
        if gen:
            for _ in range(8):  # re-draw a few times to vary the target
                task, check, olen = gen(rng)
                if task not in seen:
                    return task, check, olen, {**meta, "source": "pool"}
    if skill:
        same = [t for t in suite
                if train.task_skill(t[0]) == skill and t[0] not in seen]
        if same:
            t = rng.choice(same)
            return t[0], t[1], (t[2] if len(t) > 2 else 0), \
                {**meta, "source": "suite-skill"}
    rest = [t for t in suite if t[0] not in seen] or list(suite)
    if not rest:
        return None
    t = rng.choice(rest)
    return t[0], t[1], (t[2] if len(t) > 2 else 0), \
        {"bucket": cell or None, "skill": train.task_skill(t[0]),
         "source": "suite"}


def run_adaptive(run_one, suite: list, cap: int,
                 rng: random.Random | None = None, page: str = POOL_PAGE,
                 history: list | None = None, halt=None) -> list:
    """The adaptive loop: pick from current buckets → run → verdict →
    re-bucket → pick, until `cap` tasks or `halt()` trips. `run_one`
    receives (task, check, oracle_len, meta) and returns the clicklab
    rec (its 'verified'/'judge' fields feed the next pick). `history`
    seeds the buckets with recent prior runs so a new session learns
    from the last one."""
    rng = rng or random.Random()
    recs = list(history or [])
    seen = set()
    out = []
    for _ in range(cap):
        if halt is not None and halt():
            break
        buckets = train.compute_buckets(recs)
        t = pick_task(buckets, suite, rng, page=page, seen=seen)
        if t is None:
            break
        task, check, olen, meta = t
        rec = run_one(task, check, olen, meta)
        if rec is None:
            break
        recs.append(rec)
        seen.add(task)
        out.append(rec)
    return out
