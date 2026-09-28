"""U5e dev trace — emit/read roundtrip, schema, disable, rotation."""
import json
import pathlib
import tempfile
import unittest
import unittest.mock as mock

from dim import trace

SCHEMA_KEYS = {"ts", "turn", "step", "kind", "ms", "data"}


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.f = pathlib.Path(tempfile.mkdtemp()) / "trace.jsonl"
        self._p = mock.patch.object(trace, "TRACE_FILE", self.f)
        self._p.start()
        trace.reset_cache()
        self.addCleanup(self._p.stop)
        self.addCleanup(trace.reset_cache)

    def test_emit_read_roundtrip(self):
        trace.emit("t1", "listen_start", "lifecycle", {"seconds": 5},
                   ms=12)
        evs = trace.read(self.f)
        self.assertEqual(len(evs), 1)
        ev = evs[0]
        self.assertEqual(set(ev), SCHEMA_KEYS)  # parity: Rust emits same
        self.assertEqual(ev["turn"], "t1")
        self.assertEqual(ev["step"], "listen_start")
        self.assertEqual(ev["ms"], 12)
        self.assertEqual(ev["data"]["seconds"], 5)

    def test_filters(self):
        trace.emit("t1", "a", "tool")
        trace.emit("t2", "b", "tool")
        trace.emit("t1", "c", "brain")
        self.assertEqual(len(trace.read(self.f, turn="t1")), 2)
        self.assertEqual(len(trace.read(self.f, kind="brain")), 1)
        self.assertEqual(len(trace.read(self.f, turn="t1",
                                        kind="tool")), 1)
        self.assertEqual(len(trace.read(self.f, tail=1)), 1)

    def test_disabled_writes_nothing(self):
        with mock.patch.object(trace, "_cfg_flag", return_value=False):
            trace.emit("t1", "x", "tool")
        self.assertFalse(self.f.exists())

    def test_truncation(self):
        trace.emit("t1", "x", "brain", {"big": "z" * 9000})
        ev = trace.read(self.f)[0]
        self.assertLess(len(ev["data"]["big"]), 8300)
        self.assertTrue(ev["data"]["big"].endswith("…"))

    def test_rotation(self):
        self.f.write_text("x" * (11 * 1024 * 1024))
        trace.emit("t1", "x", "tool")
        prev = self.f.parent / "trace.1.jsonl"
        self.assertTrue(prev.exists())
        self.assertEqual(len(trace.read(self.f)), 1)

    def test_malformed_lines_skipped(self):
        self.f.write_text('{"ok": 1}\nnot json\n' +
                          json.dumps({"ts": "t", "turn": "a", "step": "s",
                                      "kind": "k", "ms": 0,
                                      "data": {}}) + "\n")
        self.assertEqual(len(trace.read(self.f)), 1)

    def test_new_turn_and_current(self):
        t = trace.new_turn()
        self.assertTrue(t.startswith("t"))
        self.assertEqual(trace.current(), t)

    def test_cli_parses(self):
        trace.emit("t1", "listen_start", "lifecycle", {"seconds": 5})
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = trace.main(["--tail", "5"])
        self.assertEqual(rc, 0)
        self.assertIn("listen_start", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
