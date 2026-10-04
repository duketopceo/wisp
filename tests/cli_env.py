"""Hermetic wispd CLI runner for tests (W19).

Runs the real `wispd` script as a subprocess inside a temp HOME/XDG tree
with PATH cut down to the system dirs, so nothing can reach the live
daemon, Hyprland, audio, notifications or any model service. A fake IPC
daemon (the real `ipc.Daemon` with a canned handler) can be started on
the temp socket; every command it receives is recorded in `.ipc`.
"""
import base64
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import shorttmp  # noqa: E402
from wisp import ipc  # noqa: E402


def canned(cmd: dict) -> dict:
    c = cmd.get("cmd")
    if c == "status":
        return {"ok": True, "state": {"status": "idle", "tasks": {}}}
    if c == "label":
        return {"ok": True, "result": "LABELLED " + cmd.get("label", "")}
    if c == "context":
        return {"ok": True, "result": "ctx: terminal focused"}
    if c in ("task_status", "task_cancel"):
        return {"ok": True, "result": f"{c} {cmd.get('name')}"}
    if c == "agent":
        return {"ok": True, "result": "SPAWNED " + cmd.get("task", "")}
    if c == "memory":
        return {"ok": True, "result": "memory ok " + str(
            cmd.get("arg") or cmd.get("target"))}
    if c == "suggestions":
        return {"ok": True, "suggestions": [
            {"status": "new", "title": "Open notes",
             "evidence": "3 times"}]}
    if c == "config":
        return {"ok": True, "config": {"audio": {"seconds": "60"}}}
    if c == "choice":
        if cmd.get("pick") == "stale":
            return {"ok": False, "error": "stale_prompt"}
        return {"ok": True}
    return {"ok": True}


class CliEnv:
    def __init__(self, daemon: bool = False, extra_env: dict | None = None,
                 path: str | None = None):
        self._td = shorttmp.TemporaryDirectory()
        self.home = pathlib.Path(self._td.name)
        self.ipc: list = []
        self._want_daemon = daemon
        self._daemon = None
        self.env = {
            # empty shim dir only: no notify-send, systemctl, hyprctl...
            "PATH": path if path is not None else str(self.home / "bin"),
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_STATE_HOME": str(self.home / ".local" / "state"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_RUNTIME_DIR": str(self.home / "run"),
            "WISP_OS": "linux", "WISP_JEV_ENDPOINT":
            "http://127.0.0.1:9/x", "NO_COLOR": "1", "COLUMNS": "80",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.env.update(extra_env or {})
        (self.home / "run").mkdir()
        (self.home / "run").chmod(0o700)
        (self.home / "bin").mkdir()
        self.calls = self.home / "shim-calls.log"

    def shim(self, name: str, body: str = "", code: int = 0):
        """PATH shim `name`: appends its argv to shim-calls.log, runs
        `body` (shell) and exits `code`. Nothing real is ever started."""
        f = self.home / "bin" / name
        f.write_text("#!/bin/sh\necho \"" + name + " $*\" >> \""
                     + str(self.calls) + "\"\n" + body + "\nexit "
                     + str(code) + "\n")
        f.chmod(0o755)

    def shim_calls(self) -> list:
        try:
            return self.calls.read_text().splitlines()
        except OSError:
            return []

    @property
    def data(self) -> pathlib.Path:
        return self.home / ".local" / "share" / "wisp"

    def __enter__(self):
        if self._want_daemon:
            self.start_daemon()
        return self

    def __exit__(self, *a):
        self.stop_daemon()
        self._td.cleanup()

    def start_daemon(self, handler=canned):
        def h(cmd):
            # t0 is a wall-clock stamp: not part of the transcript
            self.ipc.append({k: v for k, v in cmd.items() if k != "t0"})
            return handler(cmd)
        sock = self.home / "run" / "wisp" / "wispd.sock"
        self._daemon = ipc.Daemon(h, sock_file=sock)
        self._daemon.start()

    def stop_daemon(self):
        if self._daemon is not None:
            self._daemon.stop()
            self._daemon = None

    def seed_tasks(self):
        self.data.mkdir(parents=True, exist_ok=True)
        rows = [
            {"id": "t1", "name": "fix-bug", "task": "fix the login bug",
             "ts": "2026-10-01T10:00:00", "status": "done"},
            {"id": "t2", "name": "write-docs", "task": "draft the docs",
             "ts": "2026-10-01T11:00:00", "status": "failed"},
        ]
        (self.data / "tasks.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))

    def run(self, argv, exe: str = "wispd", stdin: str | None = None,
            timeout: int = 60):
        p = subprocess.run([sys.executable, str(ROOT / exe), *argv],
                           env=self.env, capture_output=True, text=True,
                           timeout=timeout, input=stdin)
        out = p.stdout.replace(str(self.home), "<HOME>")
        err = p.stderr.replace(str(self.home), "<HOME>")
        return p.returncode, out, err


B64 = base64.b64encode(b"line one\nline two").decode()

# name, legacy argv, canonical argv (None = same), daemon?, seed tasks?
SCENARIOS = [
    ("status", ["status"], None, True, False),
    ("status_default", [], ["status"], True, False),
    ("interrupt", ["interrupt"], None, True, False),
    ("stop", ["stop"], None, True, False),
    ("choice_plain", ["choice", "app:kitty"], None, True, False),
    ("choice_ids", ["choice", "--prompt-id", "p1", "--index", "2", "x"],
     None, True, False),
    ("choice_stale", ["choice", "stale"], None, True, False),
    ("choice_bad_index", ["choice", "--index", "x"], None, True, False),
    ("label_set", ["label", "correct", "was", "right"],
     ["label", "set", "correct", "was", "right"], True, False),
    ("label_report", ["label"], ["label", "report"], False, False),
    ("label_offline", ["label", "correct"],
     ["label", "set", "correct"], False, False),
    ("context", ["context"], None, True, False),
    ("task_status", ["task_status", "foo"], ["task", "status", "foo"],
     True, False),
    ("task_cancel", ["task_cancel", "foo"], ["task", "cancel", "foo"],
     True, False),
    ("agent", ["agent", "do", "a", "thing"],
     ["task", "run", "do", "a", "thing"], True, False),
    ("tasks", ["tasks"], ["task", "list"], False, True),
    ("tasks_empty", ["tasks"], ["task", "list"], False, False),
    ("memory", ["memory", "memory|add||x"], ["memory", "edit",
                                             "memory|add||x"], True, False),
    ("memory_write", ["memory-write", "user", B64],
     ["memory", "write", "user", B64], True, False),
    ("suggestions", ["suggestions"], ["suggest", "list"], True, False),
    ("config_show", ["config"], ["config", "show"], True, False),
    ("config_set", ["config", "set", "audio.seconds", "30"], None,
     True, False),
    ("config_set_offline", ["config", "set", "audio.seconds", "30"], None,
     False, False),
    ("config_set_bad", ["config", "set", "nokey", "30"], None, False,
     False),
    ("trigger", ["trigger", "start"], None, True, False),
    ("train", ["train"], ["train", "stats"], False, False),
    ("train_history", ["train", "history"], None, False, False),
    ("train_bank", ["train", "bank"], None, False, False),
    ("review", ["review"], ["review", "list"], False, False),
    ("learn", ["learn"], ["learn", "weekly"], False, False),
    ("fails", ["fails"], ["learn", "fails"], False, False),
    ("skills", ["skills"], ["skills", "list"], False, False),
    ("skills_import_usage", ["skills", "import"], None, False, False),
    ("recipes", ["recipes"], ["recipes", "draft"], False, False),
    ("recipes_approve_bad", ["recipes", "approve", "nope"], None, False,
     False),
    ("tele", ["tele", "24"], ["trace", "digest", "24"], False, False),
    ("trace_tail", ["trace", "--tail", "5"], ["trace", "show", "--tail",
                                              "5"], False, False),
    ("trace_latency", ["trace", "--latency"], ["trace", "show",
                                               "--latency"], False, False),
    ("theme_show", ["theme"], ["theme", "show"], False, False),
    ("theme_set", ["theme", "light"], ["theme", "set", "light"], False,
     False),
    ("theme_unknown", ["theme", "nope"], ["theme", "set", "nope"], False,
     False),
    ("models", ["models"], "skip", False, False),
]
