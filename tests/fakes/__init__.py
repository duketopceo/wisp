"""W5 fakes for the replay harness: cua-driver, Hyprland, notify-send,
systemctl --user, plus the LeakGuard. See rig.FakeSet for how a replay
fixture declares them. (The scripted HTTP model fakes — Jev, brain,
whisper, UI-TARS — live in tests/harness/fakes.py.)"""
from .bins import BinDir
from .cua import FakeCua
from .guard import LeakGuard, LeakViolation
from .hypr import FakeHypr, ok_handler
from .notify import FakeNotify
from .rig import FakeSet, NAMES
from .systemctl import FakeSystemctl

__all__ = ["BinDir", "FakeCua", "FakeHypr", "FakeNotify", "FakeSet",
           "FakeSystemctl", "LeakGuard", "LeakViolation", "NAMES",
           "ok_handler"]
