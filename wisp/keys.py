"""Keyboard submap: Esc stops, Enter confirms, number keys choose (W24).

Binds live in a Hyprland submap that Wisp enters only while a turn is
`acting` or `awaiting_choice` and leaves on every other status. Inside it
the keys are modifier-free (Esc, Enter, 1..9), which is safe precisely
because the submap swallows nothing outside those states, and clicks from
the pointer backends never take focus, so Esc stays reachable while cua
acts. The registry in wisp/hypr.py owns the Lua, the stale cleanup, the
conflict check and the shutdown leave; this module owns the policy.

  awaiting_choice, n options  Esc stop · Enter = option 1 · 1..min(n,9)
  acting / no options         Esc stop

Esc runs `fastkey.py ... interrupt`, the same IPC `interrupt` command as
`wispd interrupt`, without the cold-import cost. The agent's own `key`
steps go through Hyprland too, so they run inside `suspended()`.
Config: `[keys] submap = "true"` (default) / "false".
"""
from __future__ import annotations

import contextlib
import pathlib
import sys
import threading

from . import config, hypr

NAME = "wisp"
MAX_CHOICES = 9
ACTIVE: "Keys | None" = None   # the daemon's instance, for suspended()


def runner_for(sock) -> list:
    """argv prefix of the lightweight key client for this daemon socket."""
    return [sys.executable,
            str(pathlib.Path(__file__).with_name("fastkey.py")),
            "--sock", str(sock)]


def mode_for(status: str, n_choices: int = 0) -> str:
    if status == "awaiting_choice":
        return f"choose:{min(int(n_choices), MAX_CHOICES)}" \
            if n_choices > 0 else "stop"
    if status == "acting":
        return "stop"
    return ""


def entries(mode: str, runner: list) -> list:
    out = [hypr.SubmapBind("escape", runner + ["interrupt"],
                           then_reset=True)]
    if mode.startswith("choose:"):
        n = int(mode.partition(":")[2])
        out.append(hypr.SubmapBind("return", runner + ["choice", "1"]))
        out += [hypr.SubmapBind(str(i), runner + ["choice", str(i)])
                for i in range(1, n + 1)]
    return out


class Keys:
    def __init__(self, runner: list | None = None, log=None):
        self._runner = runner or runner_for(config.SOCK_FILE)
        self._log = log or (lambda m: None)
        self._lock = threading.RLock()
        self.mode = ""          # what the daemon wants
        self.handle = None
        self.defined = ""       # mode whose binds are defined
        self.active = False     # compositor is in our submap
        self.conflicts: list = []
        self._suspended = 0
        self._sub = None
        self._bus = None
        self._stop = threading.Event()
        self._thread = None

    # -- state-driven ---------------------------------------------
    def start(self) -> None:
        """Daemon start: clear a submap a crashed daemon left behind."""
        try:
            hypr.leave_submap(force=True)
        except hypr.HyprError as e:
            self._log(f"keys: stale submap cleanup failed: {e}")

    def sync(self, status: str, n_choices: int = 0) -> None:
        want = mode_for(status, n_choices)
        with self._lock:
            if want == self.mode:
                return
            self.mode = want
            if self._suspended:
                return          # applied when the key step ends
            self._apply()

    def _apply(self) -> None:
        if self.active:
            self._leave()
        if not self.mode:
            return
        try:
            clash = hypr.submap_conflicts(NAME)
            if clash:
                self.conflicts = clash
                self._log("keys: submap conflict, keyboard path off: "
                          + ", ".join(str(b.get("key")) for b in clash))
                return
            self.conflicts = []
            self.handle = hypr.define_submap(
                NAME, entries(self.mode, self._runner), check=False)
            self.defined = self.mode
            hypr.enter_submap(self.handle)
            self.active = True
        except (hypr.HyprError, ValueError) as e:
            self._log(f"keys: submap unavailable, voice/mouse only: {e}")

    def _leave(self) -> None:
        self.active = False
        try:
            hypr.leave_submap(force=True)
        except hypr.HyprError as e:
            self._log(f"keys: submap leave failed: {e}")

    @contextlib.contextmanager
    def suspended(self):
        """Out of the submap while the agent presses keys of its own."""
        with self._lock:
            was = self.active
            self._suspended += 1
            if was:
                self._leave()
        try:
            yield
        finally:
            with self._lock:
                self._suspended -= 1
                if self._suspended == 0 and self.mode:
                    if was and self.defined == self.mode and self.handle:
                        try:
                            hypr.enter_submap(self.handle)
                            self.active = True
                        except hypr.HyprError as e:
                            self._log(f"keys: re-enter failed: {e}")
                    else:
                        self._apply()

    # -- bus ------------------------------------------------------
    def attach(self, bus) -> threading.Thread:
        self._sub = bus.subscribe(maxsize=256)
        self._bus = bus
        view = dict(self._sub.snapshot)
        self._stop.clear()

        def run():
            self.sync(view.get("status", ""), len(view.get("choices") or []))
            while not self._stop.is_set():
                ev = self._sub.get(0.2)
                if ev is None or ev.get("type") != "state":
                    continue
                view.update(ev["diff"])
                self.sync(view.get("status", ""),
                          len(view.get("choices") or []))
        self._thread = threading.Thread(target=run, name="wisp-keys",
                                        daemon=True)
        self._thread.start()
        return self._thread

    def detach(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
        if self._sub is not None:
            try:
                self._bus.unsubscribe(self._sub)
            except Exception:
                pass
            self._sub = None

    def stop(self) -> None:
        self.detach()
        with self._lock:
            self.mode = ""
            if self.active:
                self._leave()


def suspended():
    """Module-level hook for `key` tool steps: no-op without a daemon."""
    k = ACTIVE
    return k.suspended() if k is not None else contextlib.nullcontext()
