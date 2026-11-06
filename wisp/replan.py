"""Re-plan bookkeeping for a teaching walkthrough (U5).

A walkthrough plans one to three steps from the current screen, waits for
the user to do them, looks at the screen again and plans the next few. This
module holds the pieces of that loop that have no I/O: the turn budget, the
record of controls already pointed at, the rule for dropping a step that
was already done, and the closing line when the budget runs out.
`walkthrough_run` owns the loop itself.
"""
from __future__ import annotations

import dataclasses

from . import settle
from . import step_kinds

# Steps asked of the planner per turn. The plan says "one to three" and the
# longest recorded sequence in tests/fixtures/replan (the file-export case)
# needs three consecutive steps with no screen change between them.
PLAN_STEPS = 3

# Planner calls one walkthrough may make, the first plan included. The
# recorded multi-step sequences in tests/fixtures/replan take at most four
# plans (tests/test_replan.py asserts it), so six leaves two turns for a
# user who strays and needs one correction each.
DEFAULT_TURN_BUDGET = 6
MAX_TURN_BUDGET = 20

# How the previous step ended, as the planner is told.
DONE, CONFIRMED, SKIPPED = "done", "confirmed", "skipped"
OUTCOME_TEXT = {
    DONE: "the screen showed the user did it",
    CONFIRMED: "the user said they did it",
    SKIPPED: "the user said they were stuck and moved on",
}


def turn_budget(cfg: dict) -> int:
    """`[teach] turn_budget`, clamped; a missing or bad value is the
    default, and zero is allowed (wrap up without planning)."""
    raw = (cfg.get("teach") or {}).get("turn_budget") \
        if isinstance(cfg, dict) else None
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_TURN_BUDGET
    return max(0, min(MAX_TURN_BUDGET, n))


def _key(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def opener_key(step) -> str:
    """The control a step points at, when it is one the user presses or
    rests on and the step names it; else "" (nothing to track)."""
    if getattr(step, "kind", "click") not in (step_kinds.CLICK,
                                              step_kinds.HOVER):
        return ""
    return _key(getattr(step, "label", ""))


@dataclasses.dataclass
class Session:
    """What the loop carries between planner turns. The prompt is built
    from this and the new capture alone; no conversation is kept."""

    budget: int
    pointed: list = dataclasses.field(default_factory=list)  # opener labels
    prev_kind: str = ""
    prev_outcome: str = ""

    def note_pointed(self, step) -> None:
        k = opener_key(step)
        if k and k not in self.pointed:
            self.pointed.append(k)

    def spend(self) -> None:
        self.budget = max(0, self.budget - 1)

    def admits(self, step, wt) -> bool:
        """False for a step that was already done or points at a control
        already pointed at in this walkthrough."""
        if wt.has_completed(step) or wt.has_failed(step):
            return False
        k = opener_key(step)
        return not (k and k in self.pointed)

    def dump(self) -> dict:
        return {"budget": self.budget, "pointed": list(self.pointed),
                "prev_kind": self.prev_kind,
                "prev_outcome": self.prev_outcome}

    @classmethod
    def load(cls, data, cfg: dict) -> "Session":
        d = data if isinstance(data, dict) else {}
        try:
            budget = max(0, int(d["budget"]))
        except (KeyError, TypeError, ValueError):
            budget = turn_budget(cfg)
        pointed = [str(k) for k in d.get("pointed") or ()
                   if isinstance(k, str)]
        return cls(budget, pointed, str(d.get("prev_kind") or ""),
                   str(d.get("prev_outcome") or ""))


def screen_changed(before, after) -> bool:
    """True when the user acted between two (window, frame) readings: the
    focused window changed, or the frame differs by `settle.SETTLE_DIFF`.
    A missing frame on either side says nothing about the pixels."""
    wb, fb = before
    wa, fa = after
    if _ident(wb) != _ident(wa):
        return True
    if fb is None or fa is None:
        return False
    return settle.frame_diff(fb, fa) >= settle.SETTLE_DIFF


def _ident(win) -> tuple:
    w = win if isinstance(win, dict) else {}
    return (str(w.get("address") or w.get("id") or ""),
            str(w.get("class") or ""), str(w.get("title") or ""))


def wrap_up_line(goal: str, done: int) -> str:
    """The closing line when the turn budget runs out."""
    if done:
        return (f"That's as far as I can take you in one go. You've done "
                f"{done} of the steps for {goal}. Ask me again and I'll "
                f"pick it up from what's on your screen.")
    return (f"My planning turns for a walkthrough are set to zero, so I "
            f"can't start {goal}. Raise teach turn budget in settings, "
            f"then ask again.")
