"""Step-by-step interactive walkthrough state machine (H1).

Models HeyClicky's walkthrough tutor: up to 15 steps, a running done_log
that refuses to re-issue an already-completed step, load-wait detection when
the window title contains loading markers or the accessibility element tree
is empty, a 20 s no-change timeout that prompts 'done, or stuck?' instead of
looping, Esc cancel that clears state, and a window-state diff helper.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable

MAX_STEPS = 15
NO_CHANGE_TIMEOUT_S = 20.0

LOADING_MARKERS = (
    "loading",
    "please wait",
    "connecting",
    "working...",
    "opening",
    "fetching",
    "saving...",
    "buffering",
)


def _norm_key(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


@dataclasses.dataclass
class Step:
    """One walkthrough step: spoken text + optional target point."""

    text: str
    point: dict | None = None
    label: str = ""
    key: str = ""

    def __post_init__(self) -> None:
        if not self.label and isinstance(self.point, dict):
            self.label = str(self.point.get("label", "")).strip()
        if not self.key:
            base = f"{self.text}|{self.label}" if self.label else self.text
            self.key = _norm_key(base)


def is_loading_state(window: dict | None = None,
                     tree: dict | None = None) -> bool:
    """True when window title has loading markers or element tree is empty."""
    title = ""
    if isinstance(window, dict):
        title = str(window.get("title") or window.get("name") or "").lower()
    elif isinstance(tree, dict):
        title = str(tree.get("title") or tree.get("name") or "").lower()

    if title and any(m in title for m in LOADING_MARKERS):
        return True

    if isinstance(tree, dict):
        els = tree.get("elements")
        if els is None or (isinstance(els, list) and len(els) == 0):
            return True
    elif tree is None and window is None:
        return True

    return False


def _element_sig(el: dict) -> tuple:
    label = str(
        el.get("label")
        or el.get("title")
        or el.get("name")
        or el.get("text")
        or el.get("value")
        or ""
    ).strip()
    role = str(el.get("role") or "").strip()
    frame = el.get("frame", el.get("bounds"))
    if isinstance(frame, dict):
        f_sig = (
            frame.get("x"),
            frame.get("y"),
            frame.get("width", frame.get("w")),
            frame.get("height", frame.get("h")),
        )
    elif isinstance(frame, (list, tuple)):
        f_sig = tuple(frame)
    else:
        f_sig = ()
    focused = bool(
        el.get("focused") or el.get("is_focused") or el.get("active")
    )
    checked = el.get("checked", el.get("selected", el.get("expanded")))
    return (role, label, f_sig, focused, checked)


def diff_window_state(before: dict | None, after: dict | None) -> dict:
    """Compare two window/tree snapshots and report whether a user action
    changed focus, window identity, or the accessibility element tree."""
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}

    b_win = b.get("window") if isinstance(b.get("window"), dict) else b
    a_win = a.get("window") if isinstance(a.get("window"), dict) else a

    b_cls = str(b_win.get("class") or b_win.get("app") or "")
    a_cls = str(a_win.get("class") or a_win.get("app") or "")
    b_title = str(b_win.get("title") or b_win.get("name") or "")
    a_title = str(a_win.get("title") or a_win.get("name") or "")
    b_addr = str(
        b_win.get("address")
        or b_win.get("window_id")
        or b_win.get("id")
        or ""
    )
    a_addr = str(
        a_win.get("address")
        or a_win.get("window_id")
        or a_win.get("id")
        or ""
    )

    focus_changed = (b_cls, a_cls) != ("", "") and b_cls != a_cls
    if b_addr and a_addr and b_addr != a_addr:
        focus_changed = True
    title_changed = b_title != a_title

    b_els = b.get("elements") if isinstance(b.get("elements"), list) else []
    a_els = a.get("elements") if isinstance(a.get("elements"), list) else []

    b_sigs = [_element_sig(e) for e in b_els if isinstance(e, dict)]
    a_sigs = [_element_sig(e) for e in a_els if isinstance(e, dict)]

    b_set = set(b_sigs)
    a_set = set(a_sigs)
    added = [s for s in a_sigs if s not in b_set]
    removed = [s for s in b_sigs if s not in a_set]
    elements_changed = b_sigs != a_sigs

    changed = bool(focus_changed or title_changed or elements_changed)
    return {
        "changed": changed,
        "focus_changed": focus_changed,
        "title_changed": title_changed,
        "elements_changed": elements_changed,
        "added_count": len(added),
        "removed_count": len(removed),
    }


class Walkthrough:
    """State machine for an interactive multi-step walkthrough."""

    def __init__(
        self,
        goal: str = "",
        steps: Iterable[Step | dict | str] | None = None,
        max_steps: int = MAX_STEPS,
        no_change_timeout_s: float = NO_CHANGE_TIMEOUT_S,
    ) -> None:
        self.goal = goal
        self.max_steps = int(max_steps)
        self.no_change_timeout_s = float(no_change_timeout_s)
        self.done_log: list[str] = []
        self.failed_log: list[str] = []
        self._done_keys: set[str] = set()
        self._failed_keys: set[str] = set()
        self.current_step: Step | None = None
        self.step_started_at: float = 0.0
        self.status: str = "idle"
        self.overlay_cleared: bool = False
        self._queue: list[Step] = []
        if steps:
            for s in steps:
                self.enqueue(s)

    def _coerce_step(self, step: Step | dict | str) -> Step:
        if isinstance(step, Step):
            return step
        if isinstance(step, dict):
            pt = step.get("point")
            if pt is None and "x" in step and "y" in step:
                pt = {
                    "x": step["x"],
                    "y": step["y"],
                    "label": step.get("label", ""),
                }
            return Step(
                text=str(step.get("text") or step.get("spoken") or ""),
                point=pt,
                label=str(step.get("label") or ""),
                key=str(step.get("key") or ""),
            )
        return Step(text=str(step))

    coerce_step = _coerce_step

    def enqueue(self, step: Step | dict | str) -> Step:
        s = self._coerce_step(step)
        self._queue.append(s)
        return s

    def has_completed(self, step: Step | dict | str) -> bool:
        s = self._coerce_step(step)
        return s.key in self._done_keys or s.text in self.done_log

    def has_failed(self, step: Step | dict | str) -> bool:
        s = self._coerce_step(step)
        return s.key in self._failed_keys or s.text in self.failed_log

    def issue_step(
        self,
        step: Step | dict | str | None = None,
        now: float = 0.0,
    ) -> dict:
        """Issue `step` (or the next queued step).

        Refuses to re-issue any step already in `done_log` (or `failed_log`),
        and refuses past `max_steps` with a spoken summary.
        """
        if self.status == "cancelled":
            return {
                "action": "cancelled",
                "spoken": "stopped",
                "point": None,
                "step_index": len(self.done_log),
            }

        if step is None:
            while self._queue:
                cand = self._queue.pop(0)
                if not self.has_completed(cand) and not self.has_failed(cand):
                    step = cand
                    break
            if step is None:
                self.status = "done"
                self.current_step = None
                return {
                    "action": "complete",
                    "spoken": self.summary_text(),
                    "point": None,
                    "step_index": len(self.done_log),
                    "done_log": list(self.done_log),
                }

        s = self._coerce_step(step)
        if self.has_completed(s):
            return {
                "action": "refused_already_done",
                "reason": "already_completed",
                "spoken": "",
                "step": s,
                "step_index": len(self.done_log),
                "done_log": list(self.done_log),
            }
        if self.has_failed(s):
            return {
                "action": "refused_failed",
                "reason": "already_failed",
                "spoken": "",
                "step": s,
                "step_index": len(self.done_log),
                "done_log": list(self.done_log),
            }
        if len(self.done_log) >= self.max_steps:
            self.status = "max_steps_reached"
            self.current_step = None
            return {
                "action": "max_steps_refused",
                "reason": "max_steps",
                "spoken": self.summary_text(limit_reached=True),
                "point": None,
                "step_index": len(self.done_log),
                "done_log": list(self.done_log),
            }

        self.current_step = s
        self.step_started_at = float(now)
        self.status = "awaiting_action"
        self.overlay_cleared = False
        return {
            "action": "step",
            "step": s,
            "spoken": s.text,
            "point": s.point,
            "step_index": len(self.done_log) + 1,
            "done_log": list(self.done_log),
        }

    def mark_step_done(self, step: Step | dict | str | None = None) -> None:
        s = self._coerce_step(step) if step is not None else self.current_step
        if s is None:
            return
        if not self.has_completed(s):
            self.done_log.append(s.text)
            self._done_keys.add(s.key)
        if self.current_step and self.current_step.key == s.key:
            self.current_step = None

    def mark_step_failed(self, step: Step | dict | str | None = None) -> None:
        s = self._coerce_step(step) if step is not None else self.current_step
        if s is None:
            return
        if not self.has_failed(s):
            self.failed_log.append(s.text)
            self._failed_keys.add(s.key)
        if self.current_step and self.current_step.key == s.key:
            self.current_step = None

    def observe(
        self,
        before_state: dict | None = None,
        after_state: dict | None = None,
        *,
        elapsed_s: float = 0.0,
        hypr_event: tuple[str, str] | str | None = None,
        verified: bool = True,
    ) -> dict:
        """Evaluate user progress on the active step."""
        if self.status == "cancelled":
            return {"action": "cancelled", "spoken": "stopped"}
        if self.current_step is None:
            return {"action": "idle", "spoken": ""}

        win = (
            after_state.get("window")
            if isinstance(after_state, dict)
            and isinstance(after_state.get("window"), dict)
            else after_state
        )
        if after_state is not None and is_loading_state(win, after_state):
            self.status = "loading"
            return {
                "action": "wait_load",
                "reason": "loading",
                "spoken": "",
                "step": self.current_step,
            }

        diff = diff_window_state(before_state, after_state)
        ev_changed = False
        if hypr_event:
            ev_name = (
                hypr_event[0]
                if isinstance(hypr_event, tuple)
                else str(hypr_event).partition(">>")[0]
            )
            if ev_name in (
                "activewindow",
                "activewindowv2",
                "openwindow",
                "closewindow",
                "windowtitle",
                "windowtitlev2",
                "workspace",
            ):
                ev_changed = True

        if (diff["changed"] or ev_changed) and (
            before_state is not None or hypr_event is not None
        ):
            if not verified:
                failed = self.current_step
                self.mark_step_failed(failed)
                return self.issue_step()
            done_step = self.current_step
            self.mark_step_done(done_step)
            if self._queue:
                return self.issue_step()
            self.status = "step_done"
            return {
                "action": "advanced",
                "completed_step": done_step,
                "done_log": list(self.done_log),
                "step_index": len(self.done_log),
            }

        if elapsed_s >= self.no_change_timeout_s:
            self.status = "prompting_stuck"
            return {
                "action": "prompt_stuck",
                "spoken": "done, or stuck?",
                "choices": ["walkthrough:done", "walkthrough:stuck"],
                "step": self.current_step,
                "done_log": list(self.done_log),
            }

        self.status = "awaiting_action"
        return {
            "action": "wait",
            "spoken": "",
            "step": self.current_step,
            "done_log": list(self.done_log),
        }

    def cancel(self, state=None) -> dict:
        """Handle Esc cancel: clear walkthrough state and overlay."""
        self.current_step = None
        self._queue.clear()
        self.status = "cancelled"
        self.overlay_cleared = True
        if state is not None:
            emit = getattr(state, "emit_event", None)
            if callable(emit):
                try:
                    emit("cua.target", x=None, y=None)
                except Exception:
                    pass
            tr = getattr(state, "transition", None)
            if callable(tr):
                try:
                    tr("idle", points=[], choices=[])
                except Exception:
                    pass
        return {
            "action": "cancelled",
            "spoken": "stopped",
            "overlay_cleared": True,
            "done_log": list(self.done_log),
        }

    def summary_text(self, limit_reached: bool = False) -> str:
        n = len(self.done_log)
        if limit_reached:
            return (
                f"reached the {self.max_steps} step limit after completing "
                f"{n} steps. ask again to continue from here."
            )
        if n == 0:
            return "walkthrough complete."
        return f"completed {n} steps: " + "; ".join(self.done_log)
