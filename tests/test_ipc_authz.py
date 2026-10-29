"""U1: IPC read/mutate command split + marked-peer refusal (R2, R13, KTD2)."""
import contextlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import unittest
from datetime import datetime, timezone
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from wisp import agents, config, ipc, mcpauth, state as state_mod  # noqa: E402


def _load_wispd():
    path = str(ROOT / "wispd")
    loader = importlib.machinery.SourceFileLoader("wispd_u1_test", path)
    spec = importlib.util.spec_from_loader("wispd_u1_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


WISPD = _load_wispd()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IpcAuthzTest(unittest.TestCase):
    def setUp(self):
        if agents._SCOPE_RE.search(agents._proc_cgroup(os.getpid())):
            self.skipTest("test process runs inside a wisp-task scope; "
                          "sleepers would inherit the cgroup mark")
        self.td = pathlib.Path(shorttmp.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.td, ignore_errors=True))
        self.tf = self.td / "tasks.jsonl"
        self.sock = self.td / "wispd.sock"
        self.st = state_mod.StateBus()
        self.addCleanup(self.st.close)
        self.cfg = config._default_cfg_dict()
        self.ctl = {
            "stop": threading.Event(),
            "busy": threading.Event(),
            "interrupt": threading.Event(),
            "choice_event": threading.Event(),
            "choice_pick": "",
            "broker": None,
            "token": None,
            "rec": None,
            "rec_lock": threading.Lock(),
        }
        self.handle = WISPD._handler(
            self.st, self.cfg, self.ctl, tasks_file=self.tf)
        self.procs = []
        self.addCleanup(self._cleanup_procs)

    def _cleanup_procs(self):
        for p in self.procs:
            try:
                p.kill()
            except OSError:
                pass
            try:
                p.wait(timeout=2)
            except Exception:
                pass
            if p.stdout:
                p.stdout.close()

    def _spawn_sleeper(self) -> subprocess.Popen:
        p = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={k: v for k, v in os.environ.items()
                 if k != "WISP_TASK_ID"})
        self.procs.append(p)
        return p

    def _register_task(self, name: str, pid: int, scope: str = "") -> dict:
        rec = {
            "id": name,
            "name": name,
            "task": f"run {name}",
            "pid": pid,
            "pstart": agents._pstart(pid),
            "scope": scope or agents._scope_unit(name),
            "cmd": "ori opencode run test",
            "status": "running",
            "refused_count": 0,
            "ts": _now_iso(),
        }
        agents._log_line(rec, self.tf)
        return rec

    def test_marked_peer_refused_on_all_mutating_cmds_and_allowed_on_reads(self):
        p = self._spawn_sleeper()
        self._register_task("bg-worker", p.pid)
        peer = {"pid": p.pid, "uid": os.getuid()}

        for mcmd in sorted(ipc.MUTATING_CMDS):
            with self.subTest(mutating=mcmd):
                resp = self.handle({"cmd": mcmd}, peer)
                self.assertFalse(resp["ok"], resp)
                self.assertEqual(resp["error"], "marked_peer_refused")
                self.assertEqual(resp["cmd"], mcmd)
                self.assertEqual(resp["task_id"], "bg-worker")

        # Unlisted command -> deny-by-default for marked peers
        unlisted = self.handle({"cmd": "future_mutating_cmd"}, peer)
        self.assertFalse(unlisted["ok"])
        self.assertEqual(unlisted["error"], "marked_peer_refused")

        # Read commands succeed for the same marked peer
        for rcmd in ("status", "task_status", "suggestions", "captures"):
            with self.subTest(read=rcmd):
                resp = self.handle({"cmd": rcmd, "name": "bg-worker"}, peer)
                self.assertNotEqual(resp.get("error"), "marked_peer_refused")
                self.assertTrue(resp.get("ok"), resp)

        # devlog: a marked peer reads timings, never what the owner said
        from wisp import devlog
        full = {"turns": [{"turn": "t1", "transcript": "open my bank",
                           "result": "ACTED (1 steps): opened",
                           "note": "wrong tab", "stages": []}],
                "misses": [{"kind": "act", "examples": ["open my bank"]}]}
        with mock.patch.object(devlog, "build", return_value=full):
            resp = self.handle({"cmd": "devlog"}, peer)
            own = self.handle({"cmd": "devlog"}, None)
        self.assertTrue(resp["ok"], resp)
        self.assertEqual(resp["turns"][0]["transcript"], "")
        self.assertEqual(resp["turns"][0]["note"], "")
        self.assertEqual(resp["misses"][0]["examples"], [])
        self.assertEqual(own["turns"][0]["transcript"], "open my bank")

        # Refused count persisted on the task record
        merged = agents._find("bg-worker", self.tf)
        self.assertEqual(
            merged["refused_count"], len(ipc.MUTATING_CMDS) + 1)

    def test_unmarked_peer_passes_mutating_and_read_commands(self):
        p = self._spawn_sleeper()
        peer = {"pid": p.pid, "uid": os.getuid()}

        # Unmarked peer is not registered in tasks.jsonl and carries no marker
        info = agents.classify_peer(peer, tasks_file=self.tf)
        self.assertFalse(info["marked"])

        for cmd in (
            {"cmd": "status"},
            {"cmd": "task_status", "name": "none"},
            {"cmd": "task_cancel", "name": "none"},
            {"cmd": "choice", "pick": "yes"},
            {"cmd": "config"},
            {"cmd": "interrupt"},
            {"cmd": "stop"},
        ):
            with self.subTest(cmd=cmd["cmd"]):
                resp = self.handle(cmd, peer)
                self.assertTrue(resp["ok"], resp)

    def test_child_and_reparented_cgroup_descendant_still_refused(self):
        parent = self._spawn_sleeper()
        self._register_task("parent-task", parent.pid)

        # Depth >= 1 child of the marked parent process
        child_script = (
            "import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            "print(c.pid,flush=True);time.sleep(60)"
        )
        parent_with_child = subprocess.Popen(
            [sys.executable, "-c", child_script],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.procs.append(parent_with_child)
        self._register_task("tree-task", parent_with_child.pid)
        grandchild_pid = int(parent_with_child.stdout.readline().strip())
        try:
            resp = self.handle(
                {"cmd": "choice", "pick": "yes"},
                {"pid": grandchild_pid, "uid": os.getuid()})
            self.assertFalse(resp["ok"])
            self.assertEqual(resp["error"], "marked_peer_refused")
            self.assertEqual(resp["task_id"], "tree-task")
        finally:
            try:
                os.kill(grandchild_pid, 9)
            except OSError:
                pass

        # Reparented helper (double-fork / env -i / systemd-run subprocess):
        # ppid is 1 and env is empty, but cgroup path stays inside the
        # registered task scope `wisp-task-parent-task.scope`.
        unmarked_proc = self._spawn_sleeper()
        reparented_peer = {
            "pid": unmarked_proc.pid,
            "uid": os.getuid(),
            "ppid": 1,
            "env": {},
            "cgroup": "0::/user.slice/user-1000.slice/user@1000.service/"
                      "app.slice/wisp-task-parent-task.scope\n",
        }
        info = agents.classify_peer(reparented_peer, tasks_file=self.tf)
        self.assertTrue(info["marked"])
        self.assertTrue(info["verified"])
        self.assertEqual(info["reason"], "cgroup_scope")
        self.assertEqual(info["task_id"], "parent-task")

        resp = self.handle({"cmd": "choice", "pick": "yes"}, reparented_peer)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "marked_peer_refused")
        self.assertEqual(resp["task_id"], "parent-task")

    def test_config_set_safety_keys_and_theme_refused_for_marked_peer(self):
        p = self._spawn_sleeper()
        self._register_task("cfg-task", p.pid)
        peer = {"pid": p.pid, "uid": os.getuid()}

        safety_resp = self.handle(
            {"cmd": "config", "set": {"agent.allow_shell": "true"}}, peer)
        self.assertFalse(safety_resp["ok"])
        self.assertEqual(safety_resp["error"], "marked_peer_refused")
        self.assertEqual(safety_resp["reason"], "safety_key")

        cua_resp = self.handle(
            {"cmd": "config", "set": {"cua.kill_switch": "false"}}, peer)
        self.assertFalse(cua_resp["ok"])
        self.assertEqual(cua_resp["error"], "marked_peer_refused")
        self.assertEqual(cua_resp["reason"], "safety_key")

        budget_resp = self.handle(
            {"cmd": "config", "set": {"budget.some_future_cap": "1"}}, peer)
        self.assertEqual(budget_resp["reason"], "safety_key")

        theme_resp = self.handle(
            {"cmd": "config", "set": {"ui.theme": "light"}}, peer)
        self.assertFalse(theme_resp["ok"])
        self.assertEqual(theme_resp["error"], "marked_peer_refused")
        self.assertEqual(theme_resp["reason"], "mutating_cmd")

    def test_spoof_attempt_with_unregistered_env_marker_is_refused(self):
        p = self._spawn_sleeper()
        # Process claims WISP_TASK_ID="not-in-registry" in its environment
        # without a matching entry in tasks.jsonl.
        spoof_peer = {
            "pid": p.pid,
            "uid": os.getuid(),
            "env": {"WISP_TASK_ID": "spoofed-task-999"},
        }
        info = agents.classify_peer(spoof_peer, tasks_file=self.tf)
        self.assertTrue(info["marked"])
        self.assertFalse(info["verified"])
        self.assertTrue(info["spoofed"])
        self.assertIsNone(info["task_id"])

        for cmd in ({"cmd": "choice", "pick": "yes"}, {"cmd": "status"}):
            resp = self.handle(cmd, spoof_peer)
            self.assertFalse(resp["ok"])
            self.assertEqual(resp["error"], "marked_peer_refused")
            self.assertEqual(resp["reason"], "unregistered_task_id")

    def test_captures_full_refused_for_marked_peer(self):
        p = self._spawn_sleeper()
        self._register_task("cap-task", p.pid)
        peer = {"pid": p.pid, "uid": os.getuid()}
        resp = self.handle(
            {"cmd": "captures", "turn_id": "t1", "full": True}, peer)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "marked_peer_refused")
        self.assertEqual(resp["reason"], "gated_read")
        self.assertEqual(agents._find("cap-task", self.tf)["refused_count"], 1)
        plain = self.handle({"cmd": "captures"}, peer)
        self.assertTrue(plain["ok"], plain)

    def test_subscribe_refused_for_spoofed_peer(self):
        spoof = {"pid": os.getpid(), "uid": os.getuid(),
                 "env": {"WISP_TASK_ID": "spoofed-task-999"}}
        srv = ipc.Daemon(self.handle, sock_file=self.sock, bus=self.st)
        srv.start()
        self.addCleanup(srv.stop)
        with mock.patch.object(ipc, "_peer_cred", return_value=spoof), \
                mock.patch.object(ipc.config, "TASKS_FILE", self.tf):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.addCleanup(s.close)
            s.settimeout(5)
            s.connect(str(self.sock))
            s.sendall(b'{"cmd":"subscribe"}\n')
            line = s.makefile().readline()
        hello = json.loads(line)
        self.assertEqual(hello["type"], "hello")
        self.assertFalse(hello["ok"])
        self.assertEqual(hello["error"], "marked_peer_refused")
        self.assertEqual(hello["reason"], "unregistered_task_id")

    def test_local_connect_verb_refuses_marked_peer(self):
        p = self._spawn_sleeper()
        self._register_task("oauth-task", p.pid)
        out = mcpauth.connect(
            "github", self.cfg,
            peer={"pid": p.pid, "uid": os.getuid()},
            tasks_file=self.tf)
        self.assertTrue(out.startswith("REFUSED"), out)
        self.assertEqual(agents._find("oauth-task", self.tf)["refused_count"], 1)

    def test_unix_socket_so_peercred_end_to_end(self):
        srv = ipc.Daemon(self.handle, sock_file=self.sock, bus=self.st)
        srv.start()
        self.addCleanup(srv.stop)

        # Unmarked client over AF_UNIX succeeds on both read and mutating
        r_ok = ipc.send({"cmd": "status"}, sock_file=self.sock)
        self.assertTrue(r_ok["ok"])
        c_ok = ipc.send({"cmd": "choice", "pick": "yes"}, sock_file=self.sock)
        self.assertTrue(c_ok["ok"])

        # Register current process as a running task -> SO_PEERCRED marks it
        # (on macOS where SO_PEERCRED is absent, supply peer cred via patch).
        self._register_task("self-task", os.getpid())
        cred_ctx = (
            contextlib.nullcontext()
            if hasattr(socket, "SO_PEERCRED")
            else mock.patch.object(
                ipc, "_peer_cred",
                return_value={"pid": os.getpid(), "uid": os.getuid()})
        )
        with cred_ctx:
            r_read = ipc.send({"cmd": "captures"}, sock_file=self.sock)
            self.assertTrue(r_read["ok"])
            r_mut = ipc.send({"cmd": "choice", "pick": "yes"}, sock_file=self.sock)
            self.assertFalse(r_mut["ok"])
            self.assertEqual(r_mut["error"], "marked_peer_refused")


if __name__ == "__main__":
    unittest.main()
