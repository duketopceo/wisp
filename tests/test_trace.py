"""U5e dev trace — emit/read roundtrip, schema, disable, rotation."""
import json
import pathlib
import tempfile
import unittest
import unittest.mock as mock
from datetime import datetime, timedelta, timezone

from wisp import trace

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


class FakeClock:
    """Monotonic + wall clocks the test advances by hand (ns)."""
    def __init__(self):
        self.mono = 1_000_000_000_000
        self.wall = 1_700_000_000_000_000_000

    def advance_ms(self, ms):
        self.mono += int(ms * 1e6)
        self.wall += int(ms * 1e6)


class SpansTest(unittest.TestCase):
    def setUp(self):
        self.f = pathlib.Path(tempfile.mkdtemp()) / "trace.jsonl"
        p = mock.patch.object(trace, "TRACE_FILE", self.f)
        p.start()
        trace.reset_cache()
        self.addCleanup(p.stop)
        self.addCleanup(trace.reset_cache)
        self.clk = FakeClock()

    def _spans(self, t0_ns=None):
        return trace.Spans(t0_ns=t0_ns, clock=lambda: self.clk.mono,
                           wall=lambda: self.clk.wall)

    def _span_events(self, turn="tA"):
        return {e["step"]: e for e in trace.read(self.f, turn=turn,
                                                 kind="span")}

    def test_press_is_listening_publish_minus_client_t0(self):
        t0 = self.clk.wall            # client stamped the keypress
        self.clk.advance_ms(7)        # key-to-daemon latency
        sp = self._spans(t0_ns=t0)
        self.clk.advance_ms(13)       # daemon publishes listening
        sp.record("press", sp.t0)
        sp.bind("tA")
        ev = self._span_events()["press"]
        self.assertEqual(ev["ms"], 20)
        self.assertEqual(ev["data"]["t0_source"], "client")
        self.assertEqual(ev["data"]["offset_ms"], 20)

    def test_no_t0_starts_at_receipt_and_is_flagged(self):
        sp = self._spans()
        self.clk.advance_ms(9)
        sp.record("press", sp.t0)
        sp.bind("tA")
        ev = self._span_events()["press"]
        self.assertEqual(ev["ms"], 9)
        self.assertEqual(ev["data"]["t0_source"], "daemon")

    def test_implausible_client_t0_falls_back_to_daemon(self):
        for bad in (self.clk.wall + 5_000_000_000,      # future
                    self.clk.wall - 120_000_000_000,    # two minutes old
                    "garbage", 0):
            sp = self._spans(t0_ns=bad)
            self.assertEqual(sp.t0_source, "daemon", bad)

    def test_spans_emit_once_bound_and_not_before(self):
        sp = self._spans()
        sp.record("press", sp.t0)
        self.assertEqual(trace.read(self.f), [])
        sp.bind("tA")
        self.assertEqual(len(trace.read(self.f, kind="span")), 1)
        self.clk.advance_ms(5)
        sp.record("stt", sp.t0)
        self.assertEqual(len(trace.read(self.f, kind="span")), 2)

    def test_release_offsets_use_release_t0(self):
        sp = self._spans()
        sp.bind("tA")
        self.clk.advance_ms(3000)                   # user speaks
        sp.set_release(self.clk.wall)
        self.clk.advance_ms(4)
        sp.record("release", sp.rel0)
        self.clk.advance_ms(600)
        sp.record("stt", sp.rel0)
        evs = self._span_events()
        self.assertEqual(evs["release"]["ms"], 4)
        self.assertEqual(evs["stt"]["ms"], 604)
        self.assertEqual(evs["stt"]["data"]["offset_ms"], 3604)

    def test_first_step_fires_once_on_first_tool_call(self):
        sp = self._spans()
        sp.bind("tA")
        sp.arm("first_step")
        self.clk.advance_ms(80)
        trace.emit("tA", "tool_call", "tool", {"name": "launch"})
        self.clk.advance_ms(80)
        trace.emit("tA", "tool_call", "tool", {"name": "click"})
        evs = trace.read(self.f, turn="tA", kind="span")
        steps = [e for e in evs if e["step"] == "first_step"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["ms"], 80)

    def test_unarmed_tool_call_records_nothing(self):
        sp = self._spans()
        sp.bind("tA")
        trace.emit("tA", "tool_call", "tool", {})
        self.assertEqual(trace.read(self.f, kind="span"), [])

    def test_timed_context_manager_records_sub_span(self):
        sp = self._spans()
        sp.bind("tA")
        with sp.timed("screenshot"):
            self.clk.advance_ms(200)
        self.assertEqual(self._span_events()["screenshot"]["ms"], 200)

    def test_legacy_timing_derived_from_spans(self):
        sp = self._spans()
        sp.bind("tA")
        sp.set_release(self.clk.wall)
        self.clk.advance_ms(600)
        sp.record("stt", sp.rel0)
        self.clk.advance_ms(200)
        sp.record("context", sp.mark_ns("stt"))
        self.clk.advance_ms(50)
        sp.record("route", sp.mark_ns("context"))
        self.clk.advance_ms(100)
        sp.record("done", sp.rel0)
        self.assertEqual(sp.legacy_timing(),
                         {"record_ms": 0, "stt_ms": 600, "jev_ms": 250,
                          "act_ms": 950})


class LatencyReportTest(unittest.TestCase):
    def setUp(self):
        self.f = pathlib.Path(tempfile.mkdtemp()) / "trace.jsonl"
        self.now = datetime.now(timezone.utc)

    def _turn(self, turn, spans, age_h=0.0):
        ts = (self.now - timedelta(hours=age_h)).isoformat()
        with open(self.f, "a") as fh:
            for step, ms in spans.items():
                fh.write(json.dumps({"ts": ts, "turn": turn, "step": step,
                                     "kind": "span", "ms": ms,
                                     "data": {"offset_ms": ms,
                                              "t0_source": "client"}})
                         + "\n")

    def test_p50_p90_nearest_rank_and_miss_marker(self):
        from wisp import telemetry
        for i in range(10):          # press 10..100 ms, budget p50 25
            self._turn(f"t{i}", {"press": (i + 1) * 10})
        rep = telemetry.latency_report(trace_file=self.f)
        row = {r["id"]: r for r in rep["rows"]}["P1"]
        self.assertEqual(row["n"], 10)
        self.assertEqual(row["p50"], 50)
        self.assertEqual(row["p90"], 90)
        self.assertEqual(row["budget_p50"], 25)
        self.assertEqual(row["verdict"], "MISS")
        self.assertIn("MISS", telemetry.latency_text(trace_file=self.f))

    def test_within_budget_is_ok(self):
        from wisp import telemetry
        for i in range(10):
            self._turn(f"t{i}", {"press": 10 + i})
        row = {r["id"]: r for r in telemetry.latency_report(
            trace_file=self.f)["rows"]}["P1"]
        self.assertEqual(row["verdict"], "ok")

    def test_p90_beyond_1_5x_budget_is_a_miss_even_if_p50_passes(self):
        from wisp import telemetry
        vals = [10] * 8 + [100, 100]    # p50 10 ok, p90 100 > 1.5 * 25
        for i, v in enumerate(vals):
            self._turn(f"t{i}", {"press": v})
        row = {r["id"]: r for r in telemetry.latency_report(
            trace_file=self.f)["rows"]}["P1"]
        self.assertEqual(row["p50"], 10)
        self.assertEqual(row["verdict"], "MISS")

    def test_route_and_e2e_compose_per_turn(self):
        from wisp import telemetry
        self._turn("t1", {"stt": 600, "context": 100, "route": 50,
                          "first_token": 300})
        rows = {r["id"]: r for r in telemetry.latency_report(
            trace_file=self.f)["rows"]}
        self.assertEqual(rows["P4"]["p50"], 150)    # context + route
        self.assertEqual(rows["E2E"]["p50"], 1050)  # key up -> 1st token
        self.assertEqual(rows["E2E"]["verdict"], "ok")

    def test_since_filters_old_turns(self):
        from wisp import telemetry
        self._turn("old", {"press": 900}, age_h=48)
        self._turn("new", {"press": 10})
        rep = telemetry.latency_report(since_hours=24, trace_file=self.f)
        row = {r["id"]: r for r in rep["rows"]}["P1"]
        self.assertEqual(row["n"], 1)
        self.assertEqual(row["p50"], 10)

    def test_path_without_data_reports_no_data(self):
        from wisp import telemetry
        self._turn("t1", {"press": 10})
        txt = telemetry.latency_text(trace_file=self.f)
        self.assertIn("P6", txt)
        self.assertIn("no data", txt)

    def test_cli_latency_flag_prints_report(self):
        import io, contextlib
        self._turn("t1", {"press": 10})
        buf = io.StringIO()
        with mock.patch.object(trace, "TRACE_FILE", self.f), \
             contextlib.redirect_stdout(buf):
            rc = trace.main(["--latency", "--since", "24h"])
        self.assertEqual(rc, 0)
        self.assertIn("P1", buf.getvalue())

    def test_parse_since(self):
        from wisp import telemetry
        self.assertEqual(telemetry.parse_since("24h"), 24)
        self.assertEqual(telemetry.parse_since("2d"), 48)
        self.assertEqual(telemetry.parse_since("90m"), 1.5)
        self.assertEqual(telemetry.parse_since("6"), 6)


if __name__ == "__main__":
    unittest.main()
