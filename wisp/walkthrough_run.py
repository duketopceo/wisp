"""Run a spoken, pointed, click-detected walkthrough (Phase 7 / R7).

"Walk me through setting up a git repo" plans up to 15 steps with the
brain, then drives `walkthrough.Walkthrough` one step at a time: speak the
step, point at its target, wait for the user to do it (the focused window
or its title changes), advance, and ask "done, or stuck?" when nothing
changes for 20 s. Wisp never clicks or types here; the user does.

Pointing is label-first: a step names the control by its on-screen label,
and the label is resolved through the exact grounding providers (the app's
control channel, then the accessibility tree) before the model's own
coordinates are trusted. A resolved element that covers a large part of
the screen is a container, not the control, and is skipped.
"""
from __future__ import annotations

import json
import re
import time

from . import walkthrough as _wt

_INTENT = re.compile(
    r"^\s*(?:(?:hey\s+)?wisp[,\s]+)?(?:please\s+)?"
    r"(?:walk\s+me\s+through|guide\s+me\s+through|take\s+me\s+through|"
    r"teach\s+me\s+how\s+to|step\s+by\s+step(?:\s+how)?\s+(?:to|for))\s+"
    r"(.+?)[\s.!?]*$", re.IGNORECASE | re.DOTALL)
_DEMO = re.compile(
    r"^\s*(?:(?:hey\s+)?wisp[,\s]+)?(?:please\s+)?"
    r"(?:demonstrate|demo\s+me)\s+(?:how\s+to\s+)?(.+?)[\s.!?]*$",
    re.IGNORECASE | re.DOTALL)
DEMO_PREFIX = "demonstrate: "

POLL_S = 0.5
EXACT_PROVIDERS = "control,a11y"      # label-first: no pixels, no model
CONTAINER_FRACTION = 0.35             # bigger than this is a container


def walk_intent(text: str) -> str | None:
    """The goal in "walk me through X" style requests, else None."""
    m = _INTENT.match(text or "")
    goal = m.group(1).strip() if m else ""
    return goal or None


def demo_intent(text: str) -> str | None:
    """The goal in "demonstrate X" requests: Wisp narrates and points at
    every step in one go, and the user does nothing."""
    m = _DEMO.match(text or "")
    goal = m.group(1).strip() if m else ""
    return goal or None


def split_mode(detail: str) -> tuple:
    """(goal, demonstrate) from a route detail made by `route_detail`."""
    d = detail or ""
    if d.startswith(DEMO_PREFIX):
        return d[len(DEMO_PREFIX):], True
    return d, False


# -- planning -----------------------------------------------------------

_PROMPT = (
    "You guide a user through a task on their Linux desktop, one step at "
    "a time. The user does every step themselves; you never click. "
    "Reply with ONLY a JSON object: {\"steps\": [{\"say\": \"one short "
    "spoken instruction\", \"label\": \"the exact on-screen text of the "
    "control to use, or empty\"}]}. At most %d steps. The first step must "
    "be doable from the current screen. Keep each \"say\" under 25 words, "
    "plain speech, no markdown. Task: %s")


def parse_steps(raw: str, max_steps: int = _wt.MAX_STEPS) -> list:
    """Steps from a model reply: the first JSON object in `raw`, tolerant
    of code fences and prose around it. Bad entries are dropped."""
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    items = data.get("steps") if isinstance(data, dict) else None
    out = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, str):
            it = {"say": it}
        if not isinstance(it, dict):
            continue
        say = " ".join(str(it.get("say") or it.get("text") or "").split())
        if not say:
            continue
        label = " ".join(str(it.get("label") or "").split())[:80]
        point = None
        if isinstance(it.get("x"), (int, float)) \
                and isinstance(it.get("y"), (int, float)):
            point = {"x": int(it["x"]), "y": int(it["y"]), "label": label}
        out.append(_wt.Step(text=say, point=point, label=label))
        if len(out) >= max_steps:
            break
    return out


def plan(goal: str, cfg: dict, image_b64: str | None = None,
         chat=None, skill: str = "") -> list:
    from . import brain
    if chat is None:
        chat = brain.chat
    content = _PROMPT % (_wt.MAX_STEPS, goal)
    if skill:
        content += ("\n\nNotes about the app on screen (use them, do not "
                    "read them out):\n" + skill)
    if image_b64 and brain.supports_vision(cfg):
        url = image_b64 if image_b64.startswith("data:") \
            else f"data:image/png;base64,{image_b64}"
        content = [{"type": "text", "text": content},
                   {"type": "image_url", "image_url": {"url": url}}]
    out = chat([{"role": "user", "content": content}], cfg, timeout=45)
    return parse_steps(out.get("content", ""))


# -- label-first snapping ------------------------------------------------

def _screen_area(monitors) -> float:
    return float(sum(m.get("width", 0) / (m.get("scale") or 1)
                     * m.get("height", 0) / (m.get("scale") or 1)
                     for m in monitors or ()))


def snap_point(step, cfg: dict, *, ground=None, monitors=None) -> dict | None:
    """Where to point for `step`: the labelled element first, else the
    model's own coordinates, else nothing."""
    label = (step.label or "").strip()
    if label:
        if ground is None:
            from . import grounding
            ground = grounding.ground_target
        gcfg = {**cfg, "ground": {**(cfg.get("ground") or {}),
                                  "providers": EXACT_PROVIDERS}}
        try:
            t = ground(label, gcfg)
        except Exception:
            t = None
        if t is not None and not _is_container(t, monitors):
            return {"x": int(t.x), "y": int(t.y), "label": label}
    pt = step.point
    if isinstance(pt, dict) and "x" in pt and "y" in pt:
        return {"x": int(pt["x"]), "y": int(pt["y"]),
                "label": str(pt.get("label") or label)}
    return None


def _is_container(target, monitors) -> bool:
    rect = getattr(target, "rect", None)
    if not rect or len(rect) < 4:
        return False
    if monitors is None:
        from . import points
        monitors = points.monitors()
    area = _screen_area(monitors)
    return bool(area) and (rect[2] * rect[3]) / area > CONTAINER_FRACTION


# -- running -------------------------------------------------------------

class _Env:
    """The seams a run touches; tests replace them."""

    def __init__(self, cfg, state=None, speak=None, window=None,
                 sleep=time.sleep, clock=time.monotonic, check=None,
                 interrupted=None):
        self.cfg, self.state = cfg, state
        self._speak = speak
        self._window = window
        self.sleep, self.clock = sleep, clock
        self.interrupted = interrupted or (lambda: False)
        self._check = check

    def check(self) -> None:
        if self._check is not None:
            self._check()
        else:
            from . import cancel
            cancel.check()

    def window(self) -> dict:
        if self._window is not None:
            return self._window()
        from . import platform
        return platform.active_window() or {}

    def say(self, text: str, point: dict | None) -> None:
        """Publish the step (text + beacon) and speak it."""
        if self.state is not None:
            self.state.transition("speaking", answer=text,
                                  points=[point] if point else [])
        if self._speak is not None:
            self._speak(text)
            return
        from . import speech
        proc = speech.speak(text, self.cfg)
        while proc is not None and proc.poll() is None:
            self.check()
            self.sleep(0.05)


def app_skill(window: dict, match=None) -> str:
    """The seeded or learned skill text for the focused app, else ""."""
    cls = (window or {}).get("class", "")
    if not cls:
        return ""
    if match is None:
        from . import skills
        match = skills.match_app_skill
    try:
        return match(cls) or ""
    except Exception:
        return ""


def run(goal: str, cfg: dict, state=None, *, ask=None,
        image_b64: str | None = None, interrupted=None, steps=None,
        env: _Env | None = None, ground=None, monitors=None,
        demonstrate: bool = False, skill_match=None) -> str:
    """Plan and walk the user through `goal`. Returns "WALKED (n steps):
    <closing line>". With `demonstrate` every step is spoken and pointed
    at in turn without waiting for the user to act."""
    env = env or _Env(cfg, state, interrupted=interrupted)
    if steps is not None:
        planned = steps
    else:
        planned = plan(goal, cfg, image_b64,
                       skill=app_skill(env.window(), skill_match))
    if not planned:
        return ("WALKED (0 steps): I couldn't work out steps for that, "
                "try asking more specifically.")
    wt = _wt.Walkthrough(goal, planned)
    ev = wt.issue_step(now=env.clock())
    while True:
        env.check()
        if env.interrupted():
            wt.cancel(env.state)
            return f"WALKED ({len(wt.done_log)} steps): stopped."
        action = ev.get("action")
        if action == "step":
            do = _demo_step if demonstrate else _do_step
            ev = do(wt, ev, env, ask, ground, monitors)
            if ev is None:
                return (f"WALKED ({len(wt.done_log)} steps): "
                        "okay, stopping here.")
            continue
        if action in ("refused_already_done", "refused_failed"):
            ev = wt.issue_step(now=env.clock())
            continue
        n = len(wt.done_log)
        if action == "max_steps_refused":
            return f"WALKED ({n} steps): {ev.get('spoken', '')}"
        if action == "cancelled":
            return f"WALKED ({n} steps): stopped."
        if action == "advanced":
            ev = wt.issue_step(now=env.clock())
            continue
        return f"WALKED ({n} steps): all done."


def _do_step(wt, ev, env: _Env, ask, ground, monitors):
    """Announce one step and wait for the user to act. The next event
    (a step, or a terminal one), or None to stop the walkthrough."""
    step = ev["step"]
    env.say(step.text, snap_point(step, env.cfg, ground=ground,
                                  monitors=monitors))
    before = {"window": env.window()}
    t0 = env.clock()
    while True:
        env.check()
        if env.interrupted():
            wt.cancel(env.state)
            return {"action": "cancelled"}
        env.sleep(POLL_S)
        r = wt.observe(before, {"window": env.window()},
                       elapsed_s=env.clock() - t0)
        act = r.get("action")
        if act in ("wait", "wait_load"):
            continue
        if act == "prompt_stuck":
            pick = ask("Done, or stuck?", ["done", "stuck"]) if ask else None
            if pick == "done":
                wt.mark_step_done()
            elif pick == "stuck":
                wt.mark_step_failed()
            else:
                return None
            return wt.issue_step(now=env.clock())
        return r   # step | advanced | complete


def _demo_step(wt, ev, env: _Env, ask, ground, monitors):
    """Say and point at one step, then move on: nothing is clicked, typed
    or waited for."""
    step = ev["step"]
    env.say(step.text, snap_point(step, env.cfg, ground=ground,
                                  monitors=monitors))
    env.check()
    if env.interrupted():
        wt.cancel(env.state)
        return {"action": "cancelled"}
    wt.mark_step_done()
    return wt.issue_step(now=env.clock())
