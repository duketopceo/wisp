"""The first minute (B12): `wispd onboard --tour`.

Five spoken steps that show the product working: hello, watch it draw,
circle something, ask about the screen, try dictation. Each step speaks one
line, then (except hello) waits for the user to do it and passes when the
turn it caused shows up in the decision log and trace. A step that is not
done in time is skipped, not failed, and is offered again next run. Passes
are recorded in onboard.json under "tour" so the tour can resume and be
replayed from Settings. Nothing is injected into the daemon: the user's own
turns are the proof.
"""
import dataclasses
import json
import time

from . import config, trace


@dataclasses.dataclass(frozen=True)
class TourStep:
    id: str
    say: str
    needs: str = ""     # "", "draw", "ring", "answer", "dictation"


STEPS = (
    TourStep("hello", "Hi, I'm Wisp. Hold your talk key, speak, and let go; "
                      "I'll answer out loud. Let's try a few things."),
    TourStep("draw", "Hold the key and say: show me where the clock is. "
                     "I'll draw on your screen.", "draw"),
    TourStep("circle", "Now say: circle the biggest window. I'll draw a "
                       "ring around it.", "ring"),
    TourStep("ask", "Now ask about your screen. Say: what am I looking at?",
             "answer"),
    TourStep("dictation", "Last one. Say: type hello world, and I'll type "
                          "it where your cursor is.", "dictation"),
)
_BY_ID = {s.id: s for s in STEPS}


def _route(rec: dict) -> str:
    a = rec.get("answers") if isinstance(rec.get("answers"), dict) else {}
    r = a.get("route") if isinstance(a.get("route"), dict) else {}
    return str(r.get("choice") or "")


def turns_since(since_iso: str, decisions=None, trace_file=None) -> list:
    """The turns decided after `since_iso`: {turn, route, points,
    drawings} from the decision log and the trace."""
    path = decisions or config.DECISIONS
    out = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or str(rec.get("ts") or "") <= since_iso:
            continue
        pts, drws = [], []
        for ev in trace.read(trace_file, tail=10000, turn=rec.get("turn", ""),
                             kind="act"):
            if ev.get("step") == "points":
                d = ev.get("data") or ev.get("detail") or {}
                pts += d.get("points") or []
                drws += d.get("drawings") or []
        out.append({"turn": rec.get("turn", ""), "route": _route(rec),
                    "points": pts, "drawings": drws})
    return out


def passed(step: TourStep, turns: list) -> bool:
    """Did any of `turns` do what `step` asked?"""
    for t in turns:
        if step.needs == "draw" and (t["drawings"] or t["points"]):
            return True
        if step.needs == "ring" and any(
                isinstance(d, dict) and d.get("kind") == "ring"
                for d in t["drawings"]):
            return True
        if step.needs == "answer" and t["route"] == "answer":
            return True
        if step.needs == "dictation" and t["route"] == "dictation":
            return True
    return False


def run(say, turns, mark, log=print, only="", wait_s: float = 90.0,
        poll_s: float = 1.0, sleep=time.sleep, clock=time.monotonic,
        done=()) -> list:
    """Walk the tour. `say(line)` speaks and shows a line; `turns(since)`
    returns `turns_since`-shaped turns; `mark(step_id)` records a pass;
    `done` are steps already recorded (skipped unless `only` names one).
    Returns [{id, status}] with status passed | skipped | already."""
    results = []
    for step in STEPS:
        if only and step.id != only:
            continue
        if step.id in done and not only:
            results.append({"id": step.id, "status": "already"})
            continue
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        say(step.say)
        ok = not step.needs
        end = clock() + wait_s
        while not ok and clock() < end:
            sleep(poll_s)
            ok = passed(step, turns(since))
        if ok:
            mark(step.id)
        log(f"tour {step.id}: {'pass' if ok else 'skipped'}")
        results.append({"id": step.id,
                        "status": "passed" if ok else "skipped"})
    return results
