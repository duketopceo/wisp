"""TLY-430: "cua is live" means the daemon answers, not that a socket
file exists. A stale socket must make auto fall through to the next
backend; a dead socket is never reported live afterwards."""
import os
import pathlib
import socket
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import fakes  # noqa: E402

from wisp import platform, pointer, realinput  # noqa: E402

DRIVE = {"pointer": {"mode": "drive", "backend": "auto"}}


class _Home:
    def setUp(self):
        realinput._stop_for_test()
        self.td = tempfile.TemporaryDirectory()
        self.t = pathlib.Path(self.td.name)
        self.bins = fakes.BinDir(self.t / "bin")
        self.bins.install("cua-driver", {})
        self.bins.install("ydotool", {})
        self.sock = self.t / ".cache" / "cua-driver" / "cua-driver.sock"
        self.sock.parent.mkdir(parents=True)
        p = mock.patch.dict(os.environ, {
            "HOME": self.td.name, "USERPROFILE": self.td.name,
            "PATH": str(self.bins.path),
            "WISP_OS": "linux", "WISP_DESKTOP": "x11"})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.td.cleanup)
        platform._cua_probe_reset()
        self.addCleanup(platform._cua_probe_reset)

    def listen(self):
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(self.sock))
        s.listen(4)
        self.addCleanup(s.close)
        return s

    def stale(self):
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(self.sock))
        s.close()  # file remains, nobody listening


class TestCuaLive(_Home, unittest.TestCase):
    def test_stale_socket_file_is_not_live(self):
        self.stale()
        self.assertTrue(self.sock.exists())
        self.assertFalse(platform._cua_live())

    def test_listening_socket_is_live(self):
        self.listen()
        self.assertTrue(platform._cua_live())

    def test_dead_socket_not_live_after_it_dies(self):
        s = self.listen()
        self.assertTrue(platform._cua_live())
        s.close()  # daemon dies; file stays
        self.assertFalse(platform._cua_live())

    def test_negative_result_is_cached_briefly(self):
        self.stale()
        with mock.patch.object(platform, "_cua_probe",
                               return_value=False) as pr:
            platform._cua_live()
            platform._cua_live()
        self.assertEqual(pr.call_count, 1)

    def test_no_binary_is_not_live(self):
        self.listen()
        with mock.patch.object(platform, "_which", return_value=None):
            self.assertFalse(platform._cua_live())

    def test_auto_skips_stale_cua_to_next_backend(self):
        self.stale()
        b = pointer.Registry(DRIVE).select()
        self.assertIsNotNone(b)
        self.assertEqual(b.name, "ydotool")

    def test_auto_picks_cua_when_listening(self):
        self.listen()
        self.assertEqual(pointer.Registry(DRIVE).select().name, "cua")


if __name__ == "__main__":
    unittest.main()
