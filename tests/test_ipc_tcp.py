"""Experimental TCP framing and fail-closed authorization on loopback.
No authenticated native Windows IPC boundary exists yet."""
import os
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import wisp.ipc as ipc
from wisp import agents


class TestTcpTransport(unittest.TestCase):
    @unittest.skipUnless(Path("/proc/self/stat").exists() and hasattr(os, "getuid"),
                         "Linux task-ancestry fixture")
    def test_spawned_agent_cannot_erase_its_restrictions_via_tcp(self):
        script = (
            "import json,sys; from pathlib import Path; from wisp import ipc; "
            "ipc._TCP=True; sys.stdin.readline(); "
            "print(json.dumps(ipc.send("
            "{'cmd':'config','set':{'agent.allow_shell':'true'},"
            "'peer':{'pid':1,'uid':0}}, sock_file=Path(sys.argv[1]))))")
        with tempfile.TemporaryDirectory() as td:
            sock = Path(td) / "wispd.sock"
            tf = Path(td) / "tasks.jsonl"
            handler = mock.Mock(return_value={"ok": True})
            with mock.patch.object(ipc, "_TCP", True):
                d = ipc.Daemon(handler, sock_file=sock)
                d.start()
                p = None
                try:
                    p = subprocess.Popen(
                        [sys.executable, "-c", script, str(sock)],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True,
                        env={**os.environ, "WISP_TASK_ID": "tcp-agent"})
                    agents._log_line(
                        {"id": "tcp-agent", "pid": p.pid,
                         "pstart": agents._pstart(p.pid), "status": "running"},
                        tf)
                    self.assertTrue(agents.classify_peer(
                        {"pid": p.pid, "uid": os.getuid()}, tasks_file=tf)["marked"])
                    out, err = p.communicate("\n", timeout=5)
                    self.assertEqual(p.returncode, 0, err)
                    self.assertEqual(json.loads(out)["error"], "unattributed_peer")
                finally:
                    if p is not None and p.poll() is None:
                        p.kill()
                        p.communicate()
                    d.stop()
            handler.assert_not_called()

    def test_tcp_subscription_is_refused_without_state_exposure(self):
        with tempfile.TemporaryDirectory() as td:
            sock = Path(td) / "wispd.sock"
            handler = mock.Mock(return_value={"ok": True})
            with mock.patch.object(ipc, "_TCP", True):
                d = ipc.Daemon(handler, sock_file=sock)
                d.start()
                try:
                    stream = ipc.subscribe(sock_file=sock, timeout=2)
                    with self.assertRaisesRegex(ConnectionError, "unattributed_peer"):
                        next(stream)
                finally:
                    d.stop()
            handler.assert_not_called()

    @unittest.skipUnless(hasattr(socket, "SO_PEERCRED"),
                         "Linux native peer credential failure fixture")
    def test_failed_native_credentials_refuse_control(self):
        with tempfile.TemporaryDirectory() as td:
            sock = Path(td) / "wispd.sock"
            handler = mock.Mock(return_value={"ok": True})
            with mock.patch.object(ipc, "_TCP", False), \
                    mock.patch.dict(os.environ, {"WISP_OS": "linux"}), \
                    mock.patch.object(ipc, "_peer_cred", return_value=None):
                d = ipc.Daemon(handler, sock_file=sock)
                d.start()
                try:
                    r = ipc.send({"cmd": "choice", "pick": "yes"}, sock_file=sock)
                    self.assertEqual(r["error"], "unattributed_peer")
                finally:
                    d.stop()
            handler.assert_not_called()

    def test_control_authz_requires_native_peer_identity(self):
        for peer in (None, {}, {"pid": 123}, {"uid": 1000},
                     {"pid": 0, "uid": 1000}, {"pid": -1, "uid": 1000},
                     {"pid": "123", "uid": 1000},
                     {"pid": True, "uid": 1000}):
            with self.subTest(peer=peer):
                r = ipc.check_peer_authz(
                    {"cmd": "config", "set": {"agent.allow_shell": "true"}},
                    peer)
                self.assertIsNotNone(r)
                self.assertEqual(r["error"], "unattributed_peer")

    def test_tcp_control_is_refused_before_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            sock = Path(td) / "wispd.sock"
            handler = mock.Mock(return_value={"ok": True})
            with mock.patch.object(ipc, "_TCP", True):
                d = ipc.Daemon(handler, sock_file=sock)
                d.start()
                try:
                    for cmd in (
                            {"cmd": "config", "set": {"agent.allow_shell": "true"}},
                            {"cmd": "choice", "pick": "yes"},
                            {"cmd": "agent_tool", "token": "forged"},
                            {"cmd": "future_mutation"},
                            {"cmd": "stop"}):
                        with self.subTest(cmd=cmd["cmd"]):
                            r = ipc.send(cmd, sock_file=sock)
                            self.assertFalse(r["ok"])
                            self.assertEqual(r["error"], "unattributed_peer")
                finally:
                    d.stop()
            handler.assert_not_called()

    def test_tcp_refusal_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            sock = Path(td) / "wispd.sock"
            with mock.patch.object(ipc, "_TCP", True):
                d = ipc.Daemon(lambda c, peer=None: {"ok": True,
                                          "echo": c.get("cmd")},
                               sock_file=sock)
                d.start()
                try:
                    r = ipc.send({"cmd": "status"}, sock_file=sock)
                    self.assertFalse(r["ok"])
                    self.assertEqual(r["error"], "unattributed_peer")
                finally:
                    d.stop()

    def test_use_tcp_follows_os_dynamically(self):
        # _TCP is an import-time snapshot; _use_tcp() must honor a
        # later WISP_OS override so tests + dev hooks work.
        with mock.patch.object(ipc, "_TCP", False), \
                mock.patch.dict(os.environ, {"WISP_OS": "windows"}):
            self.assertTrue(ipc._use_tcp())
        with mock.patch.object(ipc, "_TCP", False), \
                mock.patch.dict(os.environ, {"WISP_OS": "linux"}):
            self.assertFalse(ipc._use_tcp())


if __name__ == "__main__":
    unittest.main()
