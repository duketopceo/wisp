"""Scheduled routines manager (H5).

Models HeyClicky's scheduled routines on top of systemd user timers:
  - `Routine` dataclass and JSON-backed `RoutineStore`
  - `generate_systemd_units(routine)` producing valid systemd user `.service`
    and `.timer` unit text with `Persistent=true` so missed runs coalesce to
    a single catch-up run instead of piling up
  - `require_first_opt_ingate` requiring explicit user opt-in on the first
    recurring routine
  - `record_routine_outcome(routine_id, ok)` marking `unread=True` on quiet
    completion (never speaking aloud unprompted) and auto-pausing the routine
    after 3 consecutive failures while telling the user once.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
import json
from pathlib import Path

from . import config, util

MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_ROUTINES_FILE = config.DATA_DIR / "routines.json"


_log = logging.getLogger(__name__)
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_BIN_RE = re.compile(r"^[A-Za-z0-9_./+@-]+$")


def _unit_value(value: str, field: str, *, escape_percent: bool = False) -> str:
    """Make `value` safe as a single systemd unit-file value.

    Control characters (CR, LF, NUL, ...) become spaces. A trailing backslash
    (a systemd line continuation) is rejected, never silently fixed. `%` is
    escaped to `%%` where systemd would expand specifiers."""
    v = _CTRL_RE.sub(" ", str(value or "")).strip()
    if v.endswith("\\"):
        raise ValueError(f"{field}: trailing backslash is not allowed in a unit value")
    if escape_percent:
        v = v.replace("%", "%%")
    return v


def _slug(text: str) -> str:
    return util.slug(text or "", max_len=36, default="routine")


@dataclasses.dataclass
class Routine:
    """A scheduled agent routine backed by a systemd user timer."""

    id: str = ""
    name: str = ""
    task: str = ""
    schedule: str = "daily"
    enabled: bool = True
    paused: bool = False
    consecutive_failures: int = 0
    unread: bool = False
    quiet: bool = True
    notified_pause: bool = False
    last_run_ts: str = ""
    last_status: str = ""
    opt_in_confirmed: bool = True

    def __post_init__(self) -> None:
        if not self.name and self.task:
            self.name = self.task[:48].strip()
        if not self.id:
            self.id = _slug(self.name or self.task or "routine")
        else:
            self.id = _slug(self.id)
        if not self.name:
            self.name = self.id
        if not self.task:
            self.task = self.name
        self.schedule = (self.schedule or "daily").strip() or "daily"
        self.consecutive_failures = max(0, int(self.consecutive_failures or 0))
        if self.paused:
            self.enabled = False

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict | "Routine") -> "Routine":
        if isinstance(data, Routine):
            return data
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in (data or {}).items() if k in known}
        return cls(**filtered)


class SystemdUnits(dict):
    """Dict of generated systemd unit texts that also supports 2-tuple
    unpacking (`service_text, timer_text = generate_systemd_units(routine)`)
    and attribute access (`.service`, `.timer`)."""

    @property
    def service(self) -> str:
        return self["service"]

    @property
    def timer(self) -> str:
        return self["timer"]

    @property
    def service_name(self) -> str:
        return self["service_name"]

    @property
    def timer_name(self) -> str:
        return self["timer_name"]

    def __iter__(self):
        yield self["service"]
        yield self["timer"]

    def __getitem__(self, key):
        if key == 0:
            return super().__getitem__("service")
        if key == 1:
            return super().__getitem__("timer")
        return super().__getitem__(key)


def generate_systemd_units(
    routine: Routine | dict,
    wispd_bin: str = "wispd",
) -> SystemdUnits:
    """Generate systemd user `.service` and `.timer` unit text for `routine`.

    Includes `Persistent=true` under `[Timer]` so missed runs while the
    machine was asleep or off coalesce into one immediate run on wake.
    """
    r = Routine.from_dict(routine)
    rid = _slug(r.id)
    if not _BIN_RE.match(str(wispd_bin or "")):
        raise ValueError(f"wispd_bin: unsafe executable name {wispd_bin!r}")
    desc = _unit_value(r.name or r.task or rid, "name",
                       escape_percent=True) or rid
    sched = _unit_value(r.schedule or "daily", "schedule",
                        escape_percent=True) or "daily"
    service_name = f"wisp-routine-{rid}.service"
    timer_name = f"wisp-routine-{rid}.timer"

    service_text = (
        "[Unit]\n"
        f"Description=Wisp scheduled routine: {desc} ({rid})\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/usr/bin/env {wispd_bin} agents run {rid}\n"
    )
    timer_text = (
        "[Unit]\n"
        f"Description=Timer for Wisp routine: {desc} ({rid})\n"
        "\n"
        "[Timer]\n"
        f"OnCalendar={sched}\n"
        "Persistent=true\n"
        f"Unit={service_name}\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return SystemdUnits(
        service=service_text,
        timer=timer_text,
        service_unit=service_text,
        timer_unit=timer_text,
        service_name=service_name,
        timer_name=timer_name,
    )


class RoutineStore:
    """JSON-backed persistence for scheduled routines and first-run opt-in."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else None

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else DEFAULT_ROUTINES_FILE

    def _read_raw(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"opt_in_granted": False, "routines": {}}
        except OSError:
            # Exists but unreadable: refuse to treat it as empty (the next
            # write would destroy it).
            raise
        except ValueError:
            # Corrupt JSON: keep the evidence aside instead of letting the
            # next save overwrite it with an empty store.
            aside = self.path.with_name(
                self.path.name + f".corrupt-{int(datetime.now().timestamp())}")
            try:
                os.replace(self.path, aside)
                _log.warning("routines store unparseable; moved to %s", aside)
            except OSError:
                _log.warning("routines store unparseable at %s", self.path)
                raise
            return {"opt_in_granted": False, "routines": {}}
        if isinstance(data, list):
            routines = {
                Routine.from_dict(item).id: Routine.from_dict(item).to_dict()
                for item in data
                if isinstance(item, dict)
            }
            return {"opt_in_granted": bool(routines), "routines": routines}
        if not isinstance(data, dict):
            return {"opt_in_granted": False, "routines": {}}
        routines = data.get("routines")
        if isinstance(routines, list):
            routines = {
                Routine.from_dict(item).id: Routine.from_dict(item).to_dict()
                for item in routines
                if isinstance(item, dict)
            }
        elif not isinstance(routines, dict):
            routines = {}
        return {
            "opt_in_granted": bool(data.get("opt_in_granted", False)),
            "routines": routines,
        }

    def _write_raw(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        fd, tmp = tempfile.mkstemp(
            dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def has_opted_in(self) -> bool:
        raw = self._read_raw()
        return bool(raw.get("opt_in_granted")) or bool(raw.get("routines"))

    def set_opted_in(self, granted: bool = True) -> None:
        raw = self._read_raw()
        raw["opt_in_granted"] = bool(granted)
        self._write_raw(raw)

    def list(self) -> list[Routine]:
        raw = self._read_raw()
        return [
            Routine.from_dict(v)
            for _, v in sorted(raw["routines"].items())
            if isinstance(v, dict)
        ]

    all = list

    def get(self, routine_id: str) -> Routine | None:
        key = _slug(routine_id)
        raw = self._read_raw()
        item = raw["routines"].get(routine_id) or raw["routines"].get(key)
        return Routine.from_dict(item) if isinstance(item, dict) else None

    def save(self, routine: Routine | dict) -> Routine:
        r = Routine.from_dict(routine)
        raw = self._read_raw()
        raw["routines"][r.id] = r.to_dict()
        self._write_raw(raw)
        return r

    add = save

    def create(
        self,
        routine_or_name: Routine | dict | str,
        task: str = "",
        schedule: str = "daily",
        *,
        opt_in: bool | None = None,
        confirm_fn=None,
        **kwargs,
    ) -> Routine | None:
        """Create and persist a routine if the first-recurrence opt-in gate
        passes. Returns None and writes nothing when opt-in is declined."""
        if isinstance(routine_or_name, (Routine, dict)):
            r = Routine.from_dict(routine_or_name)
        else:
            r = Routine(
                name=str(routine_or_name),
                task=task or str(routine_or_name),
                schedule=schedule,
                **kwargs,
            )
        if not require_first_opt_ingate(
            store=self,
            opt_in=opt_in,
            confirm_fn=confirm_fn,
            routine=r,
        ):
            return None
        return self.save(r)

    def pause(self, routine_id: str) -> Routine | None:
        r = self.get(routine_id)
        if r is None:
            return None
        r.paused = True
        r.enabled = False
        r.last_status = "paused"
        return self.save(r)

    def resume(self, routine_id: str) -> Routine | None:
        r = self.get(routine_id)
        if r is None:
            return None
        r.paused = False
        r.enabled = True
        r.consecutive_failures = 0
        r.notified_pause = False
        r.last_status = "ok"
        return self.save(r)

    def mark_read(self, routine_id: str) -> Routine | None:
        r = self.get(routine_id)
        if r is None:
            return None
        r.unread = False
        return self.save(r)

    def delete(self, routine_id: str) -> bool:
        key = _slug(routine_id)
        raw = self._read_raw()
        removed = False
        for k in (routine_id, key):
            if k in raw["routines"]:
                del raw["routines"][k]
                removed = True
        if removed:
            self._write_raw(raw)
        return removed

    def record_outcome(self, routine_id: str, ok: bool) -> dict:
        return record_routine_outcome(routine_id, ok, store=self)


def _interpret_opt_in(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        return v in ("yes", "y", "true", "1", "allow", "allow_once", "always", "ok")
    return bool(value)


def require_first_opt_ingate(
    opt_in: bool | str | None = None,
    confirm_fn=None,
    store: RoutineStore | None = None,
    routine: Routine | dict | str | None = None,
) -> bool:
    """Gate the creation of the first scheduled routine on explicit user opt-in.

    - If `store` already has `opt_in_granted` (or existing routines) and no
      explicit `opt_in=False` was passed, returns True without re-prompting.
    - Otherwise checks `opt_in` (if provided) or calls `confirm_fn(prompt)`.
    - On approval, persists `opt_in_granted=True` in `store` (when given).
    - On refusal, writes nothing to `store` and returns False.
    """
    if callable(opt_in) and confirm_fn is None:
        confirm_fn = opt_in
        opt_in = None

    # Only an explicit opt_in value overrides an existing opt-in; passing a
    # confirm_fn must not re-prompt someone who already opted in.
    if store is not None and store.has_opted_in() and opt_in is None:
        return True

    if opt_in is not None:
        allowed = _interpret_opt_in(opt_in)
    elif confirm_fn is not None:
        label = ""
        if isinstance(routine, Routine):
            label = routine.name
        elif isinstance(routine, dict):
            label = str(routine.get("name") or routine.get("id") or "")
        elif isinstance(routine, str):
            label = routine
        prompt = (
            f"Allow scheduled routine '{label}' to run in the background?"
            if label
            else "Allow scheduled routines to run in the background?"
        )
        allowed = _interpret_opt_in(confirm_fn(prompt))
    elif store is not None and store.has_opted_in():
        allowed = True
    else:
        allowed = False

    if allowed and store is not None:
        store.set_opted_in(True)
    return allowed


require_first_opt_in_gate = require_first_opt_ingate


def record_routine_outcome(
    routine_id: str,
    ok: bool,
    store: RoutineStore | None = None,
    path: Path | str | None = None,
) -> dict:
    """Record a scheduled routine run result.

    - On `ok=True`: sets `unread=True` (quiet completion), resets
      `consecutive_failures=0`, never speaks aloud (`speak=False`).
    - On `ok=False`: increments `consecutive_failures`; on reaching 3
      consecutive failures (`MAX_CONSECUTIVE_FAILURES`), auto-pauses the
      routine (`paused=True`, `enabled=False`) and sets `notify_user_once=True`
      on the transition so the user is told once.
    """
    st = store if store is not None else RoutineStore(path=path)
    r = st.get(routine_id)
    if r is None:
        # Never create a routine (or an implicit opt-in) from an outcome.
        return {
            "id": routine_id,
            "ok": bool(ok),
            "error": "unknown_routine",
            "unread": False,
            "paused": False,
            "enabled": False,
            "consecutive_failures": 0,
            "auto_paused": False,
            "notify_user_once": False,
            "speak": False,
            "routine": None,
        }

    r.last_run_ts = datetime.now(timezone.utc).isoformat()
    auto_paused = False
    notify_once = False

    if ok:
        r.consecutive_failures = 0
        r.unread = True
        r.last_status = "ok"
    else:
        r.consecutive_failures += 1
        r.last_status = "failed"
        if r.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            if not r.paused:
                auto_paused = True
            r.paused = True
            r.enabled = False
            r.last_status = "paused"
            if not r.notified_pause:
                notify_once = True
                r.notified_pause = True

    st.save(r)
    return {
        "id": r.id,
        "ok": bool(ok),
        "unread": r.unread,
        "paused": r.paused,
        "enabled": r.enabled,
        "consecutive_failures": r.consecutive_failures,
        "auto_paused": auto_paused,
        "notify_user_once": notify_once,
        "speak": False,
        "routine": r,
    }
