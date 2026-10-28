"""B29: a second wispd never starts, never touches the first one's
socket, and never makes an answer be spoken twice."""
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from daemonbox import DaemonBox  # noqa: E402
from harness import runner  # noqa: E402
from wisp import instance  # noqa: E402


class Lock(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.path = self.d / "wispd.lock"
        self.addCleanup(instance.release)

    def holder_proc(self):
        """A process that holds the lock until stdin closes."""
        code = ("import sys, pathlib; sys.path.insert(0, %r);"
                "from wisp import instance;"
                "instance.acquire(pathlib.Path(%r));"
                "print('held', flush=True); sys.stdin.read()"
                % (str(ROOT), str(self.path)))
        p = subprocess.Popen([sys.executable, "-c", code],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             text=True)
        self.addCleanup(lambda: (p.stdin.close(), p.wait(10),
                                 p.stdout.close()))
        self.assertEqual(p.stdout.readline().strip(), "held")
        return p

    def test_the_lock_names_its_holder_and_blocks_a_second(self):
        p = self.holder_proc()
        with self.assertRaises(instance.AlreadyRunning) as cm:
            instance.acquire(self.path)
        self.assertEqual(cm.exception.pid, p.pid)
        self.assertIn(str(p.pid), str(cm.exception))
        self.assertEqual(instance.holder(self.path), p.pid)

    def test_the_lock_dies_with_its_holder(self):
        p = self.holder_proc()
        p.stdin.close()
        p.wait(10)
        instance.acquire(self.path)          # no stale lock after an exit
        self.assertEqual(instance.holder(self.path), os.getpid())

    def test_acquire_twice_in_one_process_is_refused_too(self):
        instance.acquire(self.path)
        with self.assertRaises(instance.AlreadyRunning):
            instance.acquire(self.path)

    def test_holder_of_a_missing_or_empty_file_is_none(self):
        self.assertIsNone(instance.holder(self.path))
        self.path.write_text("")
        self.assertIsNone(instance.holder(self.path))

    def test_the_unit_does_not_restart_into_the_running_daemon(self):
        unit = (ROOT / "scripts" / "units" / "wispd.service").read_text()
        self.assertIn(f"RestartPreventExitStatus={instance.EXIT_RUNNING}",
                      unit)

    def test_the_lock_is_taken_before_anything_else_in_the_daemon(self):
        src = (ROOT / "wispd").read_text()
        a = src.index("def run_daemon")
        body = src[a:src.index("\ndef ", a + 10)]
        self.assertLess(body.index("instance.acquire()"),
                        body.index("private.harden()"))
        self.assertLess(body.index("instance.acquire()"),
                        body.index("server.start()"))


class RealDaemon(unittest.TestCase):
    def test_a_second_daemon_exits_nonzero_and_leaves_the_socket_alone(self):
        box = DaemonBox()
        self.addCleanup(box.close)
        first = box.start()
        self.assertIsNone(first.poll(), "first daemon did not start")
        self.assertTrue(box.sock.exists())
        ino = box.sock.stat().st_ino
        second = box.run_second()
        self.assertEqual(second.returncode, instance.EXIT_RUNNING,
                         second.stderr)
        self.assertIn(f"pid {first.pid}", second.stderr)
        self.assertIn("already running", second.stderr)
        self.assertEqual(box.sock.stat().st_ino, ino, "socket was replaced")
        self.assertIsNone(first.poll(), "first daemon was disturbed")
        with socket.socket(socket.AF_UNIX) as c:       # still answers
            c.settimeout(5)
            c.connect(str(box.sock))
            c.sendall(b'{"cmd": "status"}\n')
            self.assertIn(b"{", c.recv(4096))

    def test_a_daemon_starts_again_after_the_first_stops(self):
        box = DaemonBox()
        self.addCleanup(box.close)
        first = box.start()
        first.terminate()
        first.wait(15)
        again = box.start()
        self.assertIsNone(again.poll(), again.stderr.read()
                          if again.poll() is not None else "")


class Replay(unittest.TestCase):
    def test_no_answer_is_spoken_twice_when_a_second_start_hits_mid_turn(self):
        fx = runner.load_fixture("ask")
        fx["second_start"] = True
        res = runner.run_turn(fx)
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.assertEqual(res.violations, [])
        ss = res.second_start
        self.assertEqual(ss["rc"], instance.EXIT_RUNNING, ss.get("stderr"))
        self.assertIn(f"pid {ss['holder']}", ss["stderr"])
        answers = [e["answer"] for e in res.events
                   if e["status"] == "speaking" and e.get("answer")]
        self.assertTrue(answers, "the turn never spoke")
        self.assertEqual(len(set(answers)), 1)       # one answer, once


if __name__ == "__main__":
    unittest.main()
