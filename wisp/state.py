"""Daemon state: session, pending choices, agent tasks; rendered by widgets.

Every transition atomically rewrites state.json (tmp + rename) so the shell
plugin can poll a consistent snapshot without holding the IPC socket.
"""
import json
import os
import threading
from datetime import datetime, timezone

from . import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class State:
    """Mutable daemon state with atomic state.json publication.

    status: idle | listening | transcribing | deciding | awaiting_choice |
            acting | done | error
    """

    def __init__(self, state_file=config.STATE_FILE):
        self._file = state_file
        self._lock = threading.Lock()
        self.status = "idle"
        self.transcript = ""
        self.answer = ""
        self.result = ""
        self.choices = []
        self.points = []
        self.steps = []
        self.suggestion = None
        self.guide = None  # {x, y, label, seq, mode} — ghost cursor target
        self.pending = None
        self.level = 0.0
        self.tasks = {}
        self.history = []
        self.error = ""
        self.started_at = _now()
        self._write_locked()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "transcript": self.transcript,
                "answer": self.answer,
                "result": self.result,
                "choices": list(self.choices),
                "points": list(self.points),
                "steps": list(self.steps),
                "suggestion": self.suggestion,
                "guide": self.guide,
                "level": self.level,
                "tasks": dict(self.tasks),
                "error": self.error,
                "started_at": self.started_at,
            }

    def transition(self, status: str, **fields) -> None:
        with self._lock:
            self.status = status
            # the ghost cursor only lives while acting — any exit
            # (done/error/speaking/listening) clears it so it can't
            # park stale on screen
            if status not in ("acting", "awaiting_choice") \
                    and "guide" not in fields:
                self.guide = None
            for k, v in fields.items():
                if hasattr(self, k):
                    setattr(self, k, v)
            self._write_locked()

    def set_level(self, level: float) -> None:
        with self._lock:
            self.level = level
            self._write_locked()

    def push_history(self, turn: dict, keep: int = 20) -> None:
        with self._lock:
            self.history.append(turn)
            self.history = self.history[-keep:]
            self._write_locked()

    def _write_locked(self) -> None:
        try:
            blob = json.dumps(self.snapshot_unlocked())
            if blob == getattr(self, "_last_blob", None):
                return  # unchanged — skip the write so watchers don't churn
            self._last_blob = blob
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(blob)
            os.replace(tmp, self._file)
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
            "points": list(self.points),
            "steps": list(self.steps),
            "suggestion": self.suggestion,
            "guide": self.guide,
            "level": self.level,
            "tasks": dict(self.tasks),
            "error": self.error,
            "started_at": self.started_at,
        }
