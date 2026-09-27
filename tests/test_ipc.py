#!/usr/bin/env python3
"""IPC tests: unix-socket server + client round-trips and failure modes."""
import json
import pathlib
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dim import ipc, state  # noqa: E402


def make_server(td, handler=None):
    sock = pathlib.Path(td) / "dimd.sock"
    srv = ipc.Daemon(handler or (lambda cmd: {"ok": True, "echo": cmd}),
                     sock_file=sock)
    srv.start()
    return srv, sock


class TestIpc(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            srv, sock = make_server(td)
            try:
                resp = ipc.send({"cmd": "status"}, sock_file=sock)
            finally:
                srv.stop()
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["echo"]["cmd"], "status")

    def test_malformed_json_gets_error_reply(self):
        with tempfile.TemporaryDirectory() as td:
            srv, sock = make_server(td)
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(5)
                s.connect(str(sock))
                s.sendall(b"not json\n")
                data = s.recv(65536)
                s.close()
            finally:
                srv.stop()
        resp = json.loads(data.decode())
        self.assertFalse(resp["ok"])
        self.assertIn("malformed", resp["error"])

    def test_handler_exception_returns_error(self):
        def boom(cmd):
            raise ValueError("nope")
        with tempfile.TemporaryDirectory() as td:
            srv, sock = make_server(td, boom)
            try:
                resp = ipc.send({"cmd": "x"}, sock_file=sock)
            finally:
                srv.stop()
        self.assertFalse(resp["ok"])
        self.assertIn("nope", resp["error"])

    def test_dead_socket_raises(self):
        with tempfile.TemporaryDirectory() as td:
            sock = pathlib.Path(td) / "dimd.sock"
            with self.assertRaises((ConnectionError, OSError)):
                ipc.send({"cmd": "status"}, sock_file=sock, timeout=2)

    def test_alive_false_when_no_daemon(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(
                ipc.alive(sock_file=pathlib.Path(td) / "dimd.sock"))


class TestState(unittest.TestCase):
    def test_transitions_rewrite_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "state.json"
            st = state.State(state_file=f)
            st.transition("listening")
            st.transition("deciding", transcript="open discord")
            st.transition("done", result="LAUNCHED")
            snap = json.loads(f.read_text())
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["transcript"], "open discord")
        self.assertEqual(snap["result"], "LAUNCHED")

    def test_missing_dir_created(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "deep" / "state.json"
            st = state.State(state_file=f)
            self.assertTrue(f.exists())

    def test_history_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            st = state.State(state_file=pathlib.Path(td) / "state.json")
            for i in range(30):
                st.push_history({"n": i})
            self.assertEqual(len(st.history), 20)
            self.assertEqual(st.history[-1]["n"], 29)


if __name__ == "__main__":
    unittest.main()
