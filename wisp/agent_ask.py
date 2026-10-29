"""Daemon-level ask queue (U7, KTD12).

A background agent can ask the user something (a question, or a
permission Wisp's policy marks risky) with no turn running. Items wait
in a FIFO. A pump thread offers the head to the shared
`cancel.PromptBroker` only when no turn holds it, publishes
`awaiting_choice` with a `prompt_id` and `source: "agent:<name>"`,
speaks the ask, and waits. The normal `choice` IPC answers it.

A turn keeps priority: `withdraw()` (called where a turn takes the
broker) pulls a published ask back and re-queues it at the head with
the same text; it is offered again once the daemon is idle. Every item
has a deadline: a permission expires to `REJECT`, a question to
`None`. Every ending emits `task_question` with the outcome.
"""
import threading
import time

from . import cancel as _cancel

REJECT = "reject"
ALLOW = "Allow"
NO = "No"
_SUMMARY_MAX = 80


class _Item:
    def __init__(self, helper, kind, text, choices, deadline, on_answer):
        self.helper = helper
        self.kind = kind
        self.text = str(text or "")
        self.choices = [str(c)[:80] for c in (choices or [])
                        if str(c).strip()][:6]
        self.deadline = deadline
        self.on_answer = on_answer
        self.pid = ""


def _name(helper: str) -> str:
    return helper[:1].upper() + helper[1:]


def spoken(item: _Item) -> str:
    who = _name(item.helper)
    if item.kind == "permission":
        return f"{who} wants to {item.text[:_SUMMARY_MAX]}. Allow or no?"
    text = f"{who} asks: {item.text}"
    if item.choices:
        text += " " + ", ".join(item.choices[:-1]) + (
            " or " if len(item.choices) > 1 else "") + item.choices[-1] + "?"
    return text


def options_for(item: _Item):
    """Option labels offered on the broker; None = free-text answer."""
    if item.kind == "permission":
        return [ALLOW, NO]
    return item.choices or None


class AskQueue:
    """`state` is a State/StateBus, `broker` the daemon's PromptBroker,
    `speak(text)` the speech path, `emit(name, **data)` the event bus.
    `busy()` is true while a turn runs; `clock` must be the broker's."""

    def __init__(self, state, broker, speak, emit, clock=time.monotonic,
                 busy=lambda: False, poll=0.05):
        self._state, self._broker = state, broker
        self._speak, self._emit = speak, emit
        self._clock, self._busy, self._poll = clock, busy, poll
        self._cv = threading.Condition()
        self._queue: list = []
        self._run = None        # {"item", "token", "withdrawn", "done"}
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._pump, daemon=True,
                                        name="agent-ask")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            run = self._run
            self._cv.notify_all()
        if run is not None:
            run["token"].cancel()
        if self._thread is not None:
            self._thread.join(2)

    def submit(self, helper, kind, text, choices, deadline, on_answer):
        item = _Item(helper, kind, text, choices, deadline, on_answer)
        with self._cv:
            self._queue.append(item)
            self._cv.notify_all()
        return item

    def withdraw(self) -> None:
        """A turn is about to take the broker: pull a published ask back
        (re-queued at the head by the pump) and return once the slot is
        free."""
        with self._cv:
            run = self._run
            if run is None:
                return
            run["withdrawn"] = True
        run["token"].cancel()
        run["done"].wait(2)

    # -- pump ----------------------------------------------------------

    def _ready(self) -> bool:
        if self._busy() or self._broker.pending_id:
            return False
        return self._state.snapshot().get("status") != "awaiting_choice"

    def _pump(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                item = self._queue[0] if self._queue else None
                if item is None or not self._ready():
                    self._cv.wait(self._poll)
                    continue
                self._queue.pop(0)
            if self._clock() >= item.deadline:
                self._finish(item, None, "timed_out")
                continue
            self._offer(item)

    def _offer(self, item) -> None:
        run = {"item": item, "token": _cancel.CancelToken(),
               "withdrawn": False, "done": threading.Event()}
        item.pid = _cancel.new_prompt_id()
        opts = options_for(item)
        prev = self._state.snapshot().get("status") or "idle"
        said = spoken(item)
        with self._cv:
            self._run = run
        pick = None
        try:
            self._state.transition(
                "awaiting_choice", choices=list(opts or []),
                prompt_id=item.pid, source=f"agent:{item.helper}",
                confirm={"prompt_id": item.pid, "prompt": said,
                         "timeout_s": max(0, int(item.deadline
                                                 - self._clock())),
                         "kind": item.kind})
            try:
                self._speak(said)
            except Exception:
                pass    # still answerable on the panel, still expires
            wait = self._broker.waiter(run["token"])
            pick = wait(max(0.0, item.deadline - self._clock()),
                        prompt_id=item.pid, options=opts)
        finally:
            snap = self._state.snapshot()
            if snap.get("prompt_id") == item.pid:
                clear = {"choices": [], "prompt_id": "", "source": "",
                         "confirm": None}
                # a withdrawn ask leaves the status to the turn that
                # took the slot; otherwise restore what it replaced
                self._state.transition(
                    snap["status"] if run["withdrawn"] else prev, **clear)
            with self._cv:
                self._run = None
                if run["withdrawn"]:
                    self._queue.insert(0, item)
                    self._cv.notify_all()
            run["done"].set()
        if run["withdrawn"] or self._stop.is_set():
            return
        if pick:
            self._finish(item, pick, "answered")
        elif self._clock() >= item.deadline:
            self._finish(item, None, "timed_out")
        else:
            self._finish(item, None, "declined")

    def _finish(self, item, pick, outcome) -> None:
        if pick is None and item.kind == "permission":
            pick = REJECT
        try:
            item.on_answer(pick)
        except Exception:
            pass
        try:
            # the answer text can hold a credential: outcome only
            self._emit("task_question", helper=item.helper,
                       kind=item.kind, outcome=outcome,
                       prompt_id=item.pid)
        except Exception:
            pass
