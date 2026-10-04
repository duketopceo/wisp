"""FakeSet: build the fakes a replay fixture declares.

Fixture block (all optional)::

    "fakes": {
      "cua":       {"mode": "live", "tools": {"click": {"ok": false,
                                              "error": "E_CUA_REFUSED"}}},
      "hypr":      {"replies": {"j/activewindow": {"class": "foot"}},
                    "events": ["workspace>>2"]},
      "notify":    {},
      "systemctl": {"units": {"llama-local.service": "inactive"}}
    }

``{}`` means "default behaviour"; omitting a key means that fake is not
installed (its binary is simply absent from the turn's PATH).
"""
import pathlib

from .bins import BinDir
from .cua import FakeCua
from .guard import LeakGuard
from .hypr import FakeHypr
from .notify import FakeNotify
from .systemctl import FakeSystemctl

NAMES = ("cua", "hypr", "notify", "systemctl")


def unknown_fakes(decl: dict) -> list:
    return sorted(set(decl) - set(NAMES))


class FakeSet:
    def __init__(self, decl: dict | None, root, home=None, run=None):
        decl = decl or {}
        bad = unknown_fakes(decl)
        if bad:
            raise ValueError(f"unknown fakes {bad}; known: {list(NAMES)}")
        self.decl = decl
        self.root = pathlib.Path(root)
        self.home = pathlib.Path(home or self.root / "home")
        self.run = pathlib.Path(run or self.root / "run")
        self.home.mkdir(parents=True, exist_ok=True)
        self.run.mkdir(parents=True, exist_ok=True)
        self.bins = BinDir(self.root / "fakebin")
        self.guard = LeakGuard(self.root)
        self.cua = self.hypr = self.notify = self.systemctl = None
        self._started: list = []

    def start(self):
        self.guard.install()
        d = self.decl
        if "cua" in d:
            self.cua = FakeCua(self.home, self.bins, d["cua"]).start()
            self._started.append(self.cua)
        if "hypr" in d:
            self.hypr = FakeHypr(runtime_dir=self.run, bins=self.bins,
                                 script=d["hypr"]).start()
            self._started.append(self.hypr)
        if "notify" in d:
            self.notify = FakeNotify(self.bins, d["notify"])
        if "systemctl" in d:
            self.systemctl = FakeSystemctl(self.bins, d["systemctl"])
        self.guard.check_paths(self.paths())
        return self

    def stop(self):
        for f in reversed(self._started):
            f.stop()
        self._started = []
        self.guard.uninstall()

    def paths(self) -> list:
        out = [self.bins.path]
        if self.cua:
            out.append(self.cua.sock_path)
        if self.hypr:
            out.append(self.hypr.dir)
        return out

    def env(self) -> dict:
        """Env additions for the turn child. PATH is ONLY the fake bin
        dir: no real binary is reachable."""
        e = {"PATH": str(self.bins.path)}
        if self.hypr:
            e.update(self.hypr.env())
            e["WISP_DESKTOP"] = "hyprland"
        return e

    def calls(self) -> dict:
        out = {}
        if self.cua:
            out["cua"] = [{"tool": c["tool"], "args": c["args"]}
                          for c in self.cua.calls]
        if self.hypr:
            out["hypr"] = list(self.hypr.requests)
        if self.notify:
            out["notify"] = self.notify.notifications
        if self.systemctl:
            out["systemctl"] = self.systemctl.commands()
        return out

    def violations(self) -> list:
        v = list(self.guard.violations)
        if self.systemctl:
            v += [f"systemctl system scope: {a}"
                  for a in self.systemctl.violations()]
        return v
