"""Sandbox.close reaps processes that left the spawned process group
(a browser's helpers) so their windows do not outlive the attempt."""
import importlib.util
import os
import pathlib
import signal
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "gauntlet_sandbox_t", ROOT / "scripts" / "gauntlet" / "sandbox.py")
SB = importlib.util.module_from_spec(_spec)
sys.modules["gauntlet_sandbox_t"] = SB
_spec.loader.exec_module(SB)


class Stragglers(unittest.TestCase):
    def test_close_kills_what_still_names_the_root(self):
        left = [[4242, 4243], []]
        killed = []
        box = SB.Sandbox("/tmp/sbx-root", sleep=lambda s: None,
                         stragglers=lambda root: left.pop(0),
                         kill=lambda pid, sig: killed.append((pid, sig)))
        box.close()
        self.assertEqual(killed, [(4242, signal.SIGKILL),
                                  (4243, signal.SIGKILL)])

    def test_procs_under_matches_cmdline_and_skips_self(self):
        with tempfile.TemporaryDirectory() as d:
            for pid, cmd in ((str(os.getpid()), b"x/root/y\0"),
                             ("77", b"chromium\0--user-data-dir=/root/home\0"),
                             ("78", b"chromium\0--other\0"), ("abc", b"/root")):
                p = pathlib.Path(d, pid)
                p.mkdir()
                (p / "cmdline").write_bytes(cmd)
            self.assertEqual(SB.procs_under("/root", proc=d), [77])


if __name__ == "__main__":
    unittest.main()
