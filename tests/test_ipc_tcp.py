"""Windows transport path (TCP + port file) — exercised on Linux so
the exact shipping code is proven."""
import unittest
from pathlib import Path
from unittest import mock

import wisp.ipc as ipc


class TestTcpTransport(unittest.TestCase):
    def test_tcp_roundtrip(self, *args):
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            sock = Path(td) / "wispd.sock"
            with mock.patch.object(ipc, "_TCP", True):
                d = ipc.Daemon(lambda c: {"ok": True,
                                          "echo": c.get("cmd")},
                               sock_file=sock)
                d.start()
                try:
                    r = ipc.send({"cmd": "status"}, sock_file=sock)
                    self.assertTrue(r["ok"])
                    self.assertEqual(r["echo"], "status")
                finally:
                    d.stop()


if __name__ == "__main__":
    unittest.main()
