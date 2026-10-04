"""Fake executables on a private PATH directory.

``BinDir`` owns a temp ``bin/`` dir. ``install(name, cfg)`` writes a
tiny launcher that runs ``_shim.py`` (stdlib only, no wisp import) with
the tool name; behaviour comes from ``<name>.json`` next to it, re-read
on every call so a test can change the script mid-run. Every invocation
appends one JSON line to ``calls.jsonl``.

Used as the ONLY ``PATH`` of the replayed turn, so a real binary can
never be reached: anything not faked is simply "command not found".
"""
import json
import os
import pathlib
import stat
import sys

HERE = pathlib.Path(__file__).resolve().parent


class BinDir:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "_shim.py").write_text(
            (HERE / "_shim.py").read_text())
        self.log = self.path / "calls.jsonl"
        self.log.touch()
        self._names: list = []

    def install(self, name: str, cfg: dict | None = None) -> pathlib.Path:
        p = self.path / name
        p.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            f"sys.path.insert(0, {str(self.path)!r})\n"
            "import _shim\n"
            f"sys.exit(_shim.main({name!r}))\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        self.configure(name, cfg or {})
        if name not in self._names:
            self._names.append(name)
        return p

    def configure(self, name: str, cfg: dict) -> None:
        (self.path / f"{name}.json").write_text(json.dumps(cfg))

    def config(self, name: str) -> dict:
        p = self.path / f"{name}.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def update(self, name: str, **kw) -> None:
        cfg = self.config(name)
        cfg.update(kw)
        self.configure(name, cfg)

    def remove(self, name: str) -> None:
        for suffix in ("", ".json"):
            (self.path / (name + suffix)).unlink(missing_ok=True)
        if name in self._names:
            self._names.remove(name)

    def names(self) -> list:
        return sorted(self._names)

    def calls(self, name: str | None = None) -> list:
        out = []
        for line in self.log.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                if name is None or row["bin"] == name:
                    out.append(row)
        return out

    def state_file(self, name: str) -> pathlib.Path:
        return self.path / f"{name}.state.json"
