"""Daemon state: session, pending choices, agent tasks; rendered by widgets.

`State` is the data. `StateBus` is the single publisher: every write to
state.json goes through `StateBus.publish`, which rejects writes from a
stale turn, stamps `seq` / `updated_at` / `contract_version` / `turn_id`,
coalesces high-rate fields and fans changes out to subscribers. A `State`
with no bus attached (tests, standalone use) still writes itself.
"""
import collections
import json
import os
import threading
import time
from datetime import datetime, timezone

from . import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _goal_snapshot():
    """Live goal for state.json — lazily imported (goals has no state
    dependency, safe). None most of the time."""
    try:
        from . import goals
        g = goals.snapshot()
        return g["text"][:160] if g else None
    except Exception:
        return None


CONTRACT_VERSION = 2
# Unified action lifecycle stream (contract v2, additive `actions`
# field): one entry per tool call, prompt, pick, interrupt, label and
# suggestion; the shell renders it wherever `steps` used to appear.
# Statuses are a closed set so every reader maps them the same way;
# kinds are an open set (route|tool|confirm|clarify|choice|interrupt|
# label|suggestion|question today) and render generically.
ACTION_STATUSES = frozenset(
    {"queued", "in_flight", "awaiting", "done", "failed", "cancelled"})
ACTIONS_CAP = 50
ACTION_FIELDS = frozenset({"id", "kind", "label", "status", "target",
                           "reason", "undo_ref", "at", "options",
                           "prompt_id", "delivery"})
# statuses where the model is working and the UI would otherwise sit
# silent; the bus heartbeat runs only here
BUSY = frozenset({"transcribing", "deciding", "acting"})
# fields that arrive at audio/token rate and are rate-limited by the bus
COALESCED = frozenset({"level"})


def result_status(result: str) -> str:
    """Result-string prefix -> action lifecycle status, shared by the
    route dispatcher and the act loop so prefix sets can't drift.
    Refusals/denials the gates turned away are `cancelled` (the reason
    field says which); real failures are `failed`."""
    if result.startswith(("INTERRUPTED", "SKIP", "BLOCKED",
                          "NO_ANSWER")):
        return "cancelled"
    if result.startswith(("ERROR", "REFUS", "FAIL", "ABORT", "STALL")):
        return "failed"
    return "done"


class State:
    """Mutable daemon state with atomic state.json publication.

    status: idle | listening | transcribing | deciding | awaiting_choice |
            acting | done | error
    """

    def __init__(self, state_file=config.STATE_FILE, write_initial=True):
        self._file = state_file
        self._lock = threading.Lock()
        self.status = "idle"
        self.transcript = ""
        self.answer = ""
        self.result = ""
        self.choices = []
        self.prompt_id = ""    # id of the offered choices/confirm (U9)
        self.confirm = None    # {prompt_id, prompt, timeout_s, kind} while a confirm waits (W25; kind U3)
        self.points = []
        self.steps = []
        # unified lifecycle stream — survives turns (unlike `steps`),
        # capped at the last ACTIONS_CAP entries; entries mutate by id
        self.actions = []
        self._action_seq = 0
        self.suggestion = None
        self.guide = None  # {x, y, label, seq, mode} — ghost cursor target
        self.focus = {}  # {app, title} — focused window at turn start
        self.confirmed = set()  # (tool, app) approved this session
        self.pending = None
        self.level = 0.0
        self.tasks = {}
        self.history = []
        self.error = ""
        self.error_code = ""    # closed set, wisp/errors_codes.py (U7)
        self.error_detail = ""  # raw text, local only
        self.health = {}        # {endpoint: {ok, since, latency_ms, code}}
        self.spend = {}         # {today_usd, cap_usd, ...} from ledger.py
        self.started_at = _now()
        self.heartbeat_at = None
        self._last_blob = None  # last written state.json body
        self.meta = {"seq": 0, "updated_at": self.started_at,
                     "contract_version": CONTRACT_VERSION, "turn_id": None}
        self._bus = None  # set by StateBus: all writes route through it
        if write_initial:
            self._write_locked()

    def snapshot(self) -> dict:
        with self._lock:
            return self.snapshot_unlocked()

    def apply(self, fields: dict) -> None:
        """Merge fields (status included) into the snapshot. No write —
        the caller (StateBus, or the legacy mutators below) publishes."""
        with self._lock:
            self._apply_locked(fields)

    def _apply_locked(self, fields: dict) -> None:
        status = fields.get("status")
        # the ghost cursor only lives while acting — any exit
        # (done/error/speaking/listening) clears it so it can't
        # park stale on screen
        if status is not None and status not in ("acting", "awaiting_choice") \
                and "guide" not in fields:
            self.guide = None
        for k, v in fields.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def transition(self, status: str, **fields) -> None:
        if self._bus is not None:
            self._bus.publish(None, status=status, **fields)
            return
        with self._lock:
            self._apply_locked({"status": status, **fields})
            self._write_locked()

    def set_level(self, level: float) -> None:
        if self._bus is not None:
            self._bus.publish(None, level=level)
            return
        with self._lock:
            self.level = level
            self._write_locked()

    def push_history(self, turn: dict, keep: int = 20) -> None:
        with self._lock:
            self.history.append(turn)
            self.history = self.history[-keep:]
            self._write_locked()

    # -- action stream -------------------------------------------------
    # Every surface that publishes lifecycle events holds one of State,
    # TurnState or StateBus; all three expose the same action_add /
    # action_set / action_resolve so emitters never care which they got.
    # `turn` binds the write to a turn on the bus; a bare State ignores
    # it (no turns exist without a bus).

    def action_add(self, kind: str, label: str, turn: str | None = None,
                   **kw) -> str:
        """Append an action entry; returns its id ("" when the write was
        dropped — a stale turn on the bus)."""
        if self._bus is not None:
            return self._bus.action_add(kind, label, turn=turn, **kw)
        with self._lock:
            entry = self._add_action_locked(kind, label, **kw)
            self._write_locked()
            return entry["id"]

    def action_set(self, action_id: str, turn: str | None = None,
                   **fields) -> None:
        """Patch one entry by id (status transitions, reason, ...)."""
        if self._bus is not None:
            self._bus.action_set(action_id, turn=turn, **fields)
            return
        with self._lock:
            self._set_action_locked(action_id, fields)
            self._write_locked()

    def action_resolve(self, kind: str, turn: str | None = None,
                       **fields) -> None:
        """Patch the newest `awaiting` entry of `kind` — the card the
        user just answered (suggestions resolve by kind, not id)."""
        if self._bus is not None:
            self._bus.action_resolve(kind, turn=turn, **fields)
            return
        with self._lock:
            self._resolve_action_locked(kind, fields)
            self._write_locked()

    def _add_action_locked(self, kind, label, **kw) -> dict:
        self._action_seq += 1
        status = kw.get("status", "queued")
        entry = {"id": f"a{self._action_seq}",
                 "kind": str(kind)[:40] or "action",
                 "label": str(label)[:120],
                 "status": status if status in ACTION_STATUSES
                 else "queued",
                 "target": str(kw.get("target") or "")[:160],
                 "reason": str(kw.get("reason") or "")[:200],
                 "undo_ref": kw.get("undo_ref"),
                 "at": _now()}
        options = kw.get("options")
        if options:
            entry["options"] = [str(o)[:120] for o in list(options)][:8]
        prompt_id = str(kw.get("prompt_id") or "")
        if prompt_id:
            entry["prompt_id"] = prompt_id[:80]
        delivery = str(kw.get("delivery") or "")
        if delivery:
            entry["delivery"] = delivery[:24]
        self.actions.append(entry)
        if len(self.actions) > ACTIONS_CAP:
            del self.actions[:len(self.actions) - ACTIONS_CAP]
        return entry

    def _set_action_locked(self, action_id, fields) -> bool:
        for entry in reversed(self.actions):
            if entry.get("id") == action_id:
                _merge_action(entry, fields)
                return True
        return False

    def _resolve_action_locked(self, kind, fields) -> bool:
        for entry in reversed(self.actions):
            if entry.get("kind") == kind \
                    and entry.get("status") == "awaiting":
                _merge_action(entry, fields)
                return True
        return False

    def _write_locked(self) -> None:
        if self._bus is not None:
            return  # the bus is the only writer once attached
        try:
            blob = json.dumps(self.snapshot_unlocked())
            if blob == getattr(self, "_last_blob", None):
                return  # unchanged — skip the write so watchers don't churn
            self._last_blob = blob
            atomic_write(self._file, blob)
        except OSError:
            pass

    def snapshot_unlocked(self) -> dict:
        """Snapshot fields without taking the lock (call under _lock only)."""
        return {
            "status": self.status,
            "transcript": self.transcript,
            "answer": self.answer,
            "result": self.result,
            "choices": list(self.choices),
            "prompt_id": self.prompt_id,
            "confirm": dict(self.confirm) if self.confirm else None,
            "points": list(self.points),
            "steps": list(self.steps),
            "actions": [dict(a) for a in self.actions],
            "suggestion": self.suggestion,
            "guide": self.guide,
            "focus": dict(self.focus),
            "goal": _goal_snapshot(),
            "level": self.level,
            "tasks": dict(self.tasks),
            "error": self.error,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "health": {k: dict(v) for k, v in self.health.items()},
            "spend": dict(self.spend),
            "started_at": self.started_at,
            "heartbeat_at": self.heartbeat_at,
            **self.meta,
        }


def _merge_action(entry: dict, fields: dict) -> None:
    """Patch an action-stream entry in place. `id` and unknown keys are
    ignored; `status` only moves inside the closed set."""
    for k, v in fields.items():
        if k == "id" or k not in ACTION_FIELDS:
            continue
        if k == "status":
            if v in ACTION_STATUSES:
                entry["status"] = v
        elif k == "options" and v is not None:
            entry["options"] = [str(o)[:120] for o in list(v)][:8]
        elif isinstance(v, str):
            entry[k] = v[:200]
        else:
            entry[k] = v


def atomic_write(path, blob: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(blob)
    os.replace(tmp, path)


TOPICS = frozenset({"state", "health", "tasks", "events"})


def topic_of(ev: dict) -> str:
    """Topic an event belongs to: `state` (diffs), `health`
    (health_changed), `tasks` (task_*), `events` (any other named
    event). `overflow` is delivered whatever the filter."""
    if ev.get("type") == "state":
        return "state"
    name = ev.get("name", "")
    if name == "health_changed":
        return "health"
    if name.startswith("task_"):
        return "tasks"
    return "events"


class Subscription:
    """Bounded event queue for one subscriber. A reader that falls behind
    is dropped: its queue is replaced by a final `overflow` event.
    `topics` (None = everything) filters at offer time, so events the
    subscriber never asked for cannot overflow its queue."""

    def __init__(self, maxsize: int, snapshot: dict, topics=None):
        self.maxsize = maxsize
        self.snapshot = snapshot
        self.topics = frozenset(topics) if topics is not None else None
        self.closed = False
        self._q = collections.deque()
        self._cv = threading.Condition()

    def _offer(self, ev: dict) -> bool:
        """False when the subscriber overflowed and must be removed."""
        if self.topics is not None and topic_of(ev) not in self.topics:
            return not self.closed
        with self._cv:
            if self.closed:
                return False
            if len(self._q) >= self.maxsize:
                self._q.clear()
                self._q.append({"type": "event", "name": "overflow"})
                self.closed = True
                self._cv.notify_all()
                return False
            self._q.append(ev)
            self._cv.notify_all()
            return True

    def get(self, timeout: float | None = None):
        """Next event, or None on timeout / closed-and-drained."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while not self._q:
                if self.closed:
                    return None
                left = None if deadline is None \
                    else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return None
                self._cv.wait(left)
            return self._q.popleft()

    def close(self) -> None:
        with self._cv:
            self.closed = True
            self._cv.notify_all()


class TurnState:
    """A State facade bound to one turn: writes go through the bus with
    that turn id (and are dropped once a newer turn begins); reads fall
    through to the live State. Handed to code that predates the bus
    (act loop, record sampler, TTS exit callback)."""

    def __init__(self, bus: "StateBus", turn_id: str):
        self._bus = bus
        self.turn_id = turn_id

    def transition(self, status: str, **fields) -> None:
        self._bus.publish(self.turn_id, status=status, **fields)

    def set_level(self, level: float) -> None:
        self._bus.publish(self.turn_id, level=level)

    def push_history(self, turn: dict, keep: int = 20) -> None:
        self._bus.state.push_history(turn, keep)

    def action_add(self, kind: str, label: str, **kw) -> str:
        kw.pop("turn", None)  # the facade always writes its own turn
        return self._bus.action_add(kind, label, turn=self.turn_id, **kw)

    def action_set(self, action_id: str, **fields) -> None:
        fields.pop("turn", None)
        self._bus.action_set(action_id, turn=self.turn_id, **fields)

    def action_resolve(self, kind: str, **fields) -> None:
        fields.pop("turn", None)
        self._bus.action_resolve(kind, turn=self.turn_id, **fields)

    def emit_event(self, event: str, **data) -> None:
        """Named one-off event (e.g. `cua.target`), dropped once a newer
        turn has begun, like this turn's other writes."""
        if self._bus.current_turn() == self.turn_id:
            self._bus.emit_event(event, **data)

    def snapshot(self) -> dict:
        return self._bus.snapshot()

    def __getattr__(self, name):
        return getattr(self._bus.state, name)


class StateBus:
    """The single publisher of state.json.

    Writes happen synchronously in the publishing thread (so a caller
    sees its own write on return), serialized by one lock. A small
    daemon thread only does the work nobody calls for: the trailing
    flush of a coalesced field and the busy-status heartbeat.
    """

    def __init__(self, state: State | None = None, state_file=None,
                 rate_hz: float = 12.0, heartbeat_s: float = 15.0,
                 autostart: bool = True):
        if state is None:
            state = State(state_file=state_file, write_initial=False) \
                if state_file else State(write_initial=False)
        self.state = state
        self._file = state._file
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._interval = 1.0 / rate_hz
        self._heartbeat_s = heartbeat_s
        self._turn = _new_turn_id()
        self._seq = 0
        self._last_write = 0.0
        self._last_beat = time.monotonic()
        self._dirty = False
        self._paused = False
        self._pending_diff: dict = {}
        self._subs: list[Subscription] = []
        self._stop = False
        self.write_count = 0
        self._last_core = None
        state._bus = self
        with self._lock:
            self.state.meta["turn_id"] = self._turn
            self._write_locked()
        self._thread = None
        if autostart:
            self._thread = threading.Thread(
                target=self._run, name="state-bus", daemon=True)
            self._thread.start()

    # -- turns ---------------------------------------------------------

    def begin_turn(self) -> str:
        """Issue a new turn id; writes tagged with an older id are
        dropped from here on."""
        with self._lock:
            self._turn = _new_turn_id()
            return self._turn

    def current_turn(self) -> str:
        return self._turn

    def turn(self, turn_id: str) -> TurnState:
        return TurnState(self, turn_id)

    # -- publishing ----------------------------------------------------

    def publish(self, turn_id, *, coalesce: bool = False, **fields) -> bool:
        """Merge `fields` into the snapshot and publish. `turn_id` None
        marks a daemon-level write (health, tasks, boot/shutdown) that
        is never stale. Returns False when dropped as stale. Fields
        that change nothing are a no-op (no seq bump, no write)."""
        with self._lock:
            if turn_id is not None and turn_id != self._turn:
                self._drop(turn_id, fields)
                return False
            before = self.state.snapshot()
            self.state.apply(fields)
            after = self.state.snapshot()
            diff = {k: v for k, v in after.items()
                    if before.get(k) != v and k not in _META_KEYS}
            self._cv.notify_all()  # status may have entered/left BUSY
            if not diff:
                return True
            self._pending_diff.update(diff)
            self._dirty = True
            if self._paused:
                return True
            lazy = coalesce or set(diff) <= COALESCED
            if lazy and time.monotonic() - self._last_write < self._interval:
                return True  # the bus thread flushes the tail
            self._write_locked()
            return True

    def transition(self, status: str, **fields) -> bool:
        """Daemon-level status change (not tied to a turn)."""
        return self.publish(None, status=status, **fields)

    def _drop(self, turn_id, fields) -> None:
        try:
            from . import trace
            trace.emit(turn_id, "stale_publish", "state",
                       {"current": self._turn,
                        "fields": sorted(fields)[:12]})
        except Exception:
            pass

    # -- action stream --------------------------------------------------

    def publish_action(self, turn_id, op) -> bool:
        """Run `op(state)` — an action-stream mutation — inside a
        publish: the same turn-staleness check `publish` makes, one
        write, one fan-out. `actions` diffs carry the whole (capped)
        list so a subscriber just replaces it. Returns False when
        dropped as stale (the op never ran)."""
        with self._lock:
            if turn_id is not None and turn_id != self._turn:
                self._drop(turn_id, {"actions": True})
                return False
            with self.state._lock:
                before = [dict(a) for a in self.state.actions]
                op(self.state)
                after = [dict(a) for a in self.state.actions]
            if before == after:
                return True
            self._pending_diff["actions"] = after
            self._dirty = True
            if not self._paused:
                self._write_locked()
            return True

    def action_add(self, kind: str, label: str, turn: str | None = None,
                   **kw) -> str:
        """Append an action entry; the new id, or "" when the write was
        stale-dropped (the entry never landed)."""
        box = {}

        def op(s: State) -> None:
            box["id"] = s._add_action_locked(kind, label, **kw)["id"]

        return box.get("id", "") if self.publish_action(turn, op) else ""

    def action_set(self, action_id: str, turn: str | None = None,
                   **fields) -> None:
        self.publish_action(
            turn, lambda s: s._set_action_locked(action_id, fields))

    def action_resolve(self, kind: str, turn: str | None = None,
                       **fields) -> None:
        self.publish_action(
            turn, lambda s: s._resolve_action_locked(kind, fields))

    # -- writing (call under _lock) -------------------------------------

    def _write_locked(self) -> None:
        self._seq += 1
        now = _now()
        meta = self.state.meta
        meta.update(seq=self._seq, updated_at=now,
                    contract_version=CONTRACT_VERSION,
                    turn_id=self._turn)
        snap = self.state.snapshot()
        diff, self._pending_diff = self._pending_diff, {}
        self._dirty = False
        self._last_write = time.monotonic()
        self.write_count += 1
        try:
            atomic_write(self._file, json.dumps(snap))
        except OSError:
            pass
        if diff:
            diff.update(seq=self._seq, updated_at=now, turn_id=self._turn)
            self._fan_out({"type": "state", "seq": self._seq,
                           "diff": diff})

    def _fan_out(self, ev: dict) -> None:
        for sub in list(self._subs):
            if not sub._offer(ev):
                self._subs.remove(sub)

    def emit_event(self, event: str, **data) -> None:
        """Fan a named one-off event (no state change, no seq bump) out
        to subscribers, e.g. `health_changed`."""
        with self._lock:
            self._fan_out({"type": "event", "name": event, "data": data})

    # -- pause / resume ------------------------------------------------

    def pause(self) -> None:
        """Hold writes (publishes still merge into the snapshot)."""
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        """Write the latest held snapshot once."""
        with self._lock:
            self._paused = False
            if self._dirty:
                self._write_locked()

    # -- subscribers ---------------------------------------------------

    def subscribe(self, maxsize: int = 256, topics=None) -> Subscription:
        """Snapshot and registration happen under the bus lock, so the
        snapshot's `seq` is exactly one before the first queued diff."""
        with self._lock:
            sub = Subscription(maxsize, self.state.snapshot(), topics)
            self._subs.append(sub)
            return sub

    def unsubscribe(self, sub: Subscription) -> None:
        sub.close()
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    # -- reads ---------------------------------------------------------

    def snapshot(self) -> dict:
        return self.state.snapshot()

    def __getattr__(self, name):
        # reads of live fields (status, suggestion, steps, ...) fall
        # through; guarded so a half-built bus can't recurse
        if name == "state" or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.state, name)

    # -- bus thread ----------------------------------------------------

    def _run(self) -> None:
        with self._lock:
            while not self._stop:
                now = time.monotonic()
                wait = 1.0
                if self._dirty and not self._paused:
                    due = self._last_write + self._interval - now
                    if due <= 0:
                        self._write_locked()
                        continue
                    wait = min(wait, due)
                if self.state.status in BUSY:
                    due = self._last_beat + self._heartbeat_s - now
                    if due <= 0:
                        self._last_beat = now
                        self.state.apply({"heartbeat_at": _now()})
                        self._pending_diff["heartbeat_at"] = \
                            self.state.heartbeat_at
                        self._dirty = True
                        if not self._paused:
                            self._write_locked()
                        continue
                    wait = min(wait, due)
                else:
                    self._last_beat = now
                self._cv.wait(wait)

    def close(self) -> None:
        with self._lock:
            self._stop = True
            self._cv.notify_all()
            for s in self._subs:
                s.close()
            self._subs.clear()
        if self._thread is not None \
                and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


_META_KEYS = frozenset({"seq", "updated_at", "contract_version", "turn_id"})


# -- guarded emit API --------------------------------------------------
# Emitters hold whatever state surface the caller gave them — a
# TurnState, the bus, a bare State, a Mock or None — so these go through
# getattr+try instead of trusting the method to exist.


def action_add(state, kind: str, label: str, **kw) -> str:
    """Append an action-stream entry; the new id, or "" when the
    surface can't take actions (None, a mock, an older harness)."""
    fn = getattr(state, "action_add", None)
    if not callable(fn):
        return ""
    try:
        out = fn(kind, label, **kw)
    except Exception:
        return ""
    return out if isinstance(out, str) else ""


def action_set(state, action_id: str, **fields) -> None:
    """Patch an entry by id; a "" id (dropped or unemitted) is a no-op."""
    if not action_id:
        return
    fn = getattr(state, "action_set", None)
    if not callable(fn):
        return
    try:
        fn(action_id, **fields)
    except Exception:
        pass


def action_resolve(state, kind: str, **fields) -> None:
    """Patch the newest awaiting entry of `kind` (suggestion picks)."""
    fn = getattr(state, "action_resolve", None)
    if not callable(fn):
        return
    try:
        fn(kind, **fields)
    except Exception:
        pass


def _new_turn_id() -> str:
    import secrets  # same shape as trace.new_turn(), minus its thread-local
    return f"t{secrets.token_hex(4)}"
