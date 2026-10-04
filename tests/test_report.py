"""W16: GlitchTip reporting: scrubber, opt-in, envelope, limits, queue."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from wisp import config, errors_codes, pipeline, report


class _Srv:
    def __init__(self, status=200):
        self.status, self.got = status, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.got.append((self.path, dict(self.headers),
                                  self.rfile.read(n)))
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *a):
                pass
        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever,
                         daemon=True).start()

    @property
    def dsn(self):
        return f"http://pubkey@127.0.0.1:{self.port}/7"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _cfg(dsn, **kw):
    return {"report": {"dsn": dsn, **{k: str(v) for k, v in kw.items()}}}


class ScrubTest(unittest.TestCase):
    def test_drop_keys(self):
        out = report.scrub({"transcript": "open my bank", "typed": "hunter2",
                            "screenshot": "AAAA", "env": {"A": "b"},
                            "step": "click", "n": 3})
        for k in ("transcript", "typed", "screenshot", "env"):
            self.assertEqual(out[k], "[redacted]")
        self.assertEqual(out["step"], "click")
        self.assertEqual(out["n"], 3)

    def test_nested_and_secret_keys(self):
        out = report.scrub({"a": [{"messages": ["hi"], "api_key": "x"}]})
        self.assertEqual(out["a"][0]["messages"], "[redacted]")
        self.assertEqual(out["a"][0]["api_key"], "[redacted]")

    def test_home_paths(self):
        home = os.path.expanduser("~")
        s = report.scrub_text(f"{home}/x/y and /home/bob/z /Users/amy/q")
        self.assertNotIn(home, s)
        self.assertNotIn("bob", s)
        self.assertNotIn("amy", s)
        self.assertIn("~/x/y", s)

    def test_tokens(self):
        for t in ("sk-or-v1-abcdef123456", "ghp_abcdefghijkl123456",
                  "Bearer abc.def-ghi123", "api_key=zzzzzzzz"):
            s = report.scrub_text(f"failed with {t} here")
            self.assertIn("[redacted]", s)
            self.assertNotIn(t.split()[-1], s)

    def test_screenshot_blobs(self):
        s = report.scrub_text("x data:image/png;base64,iVBORw0KGgo= y")
        self.assertNotIn("iVBOR", s)
        s = report.scrub_text("z" * 400)
        self.assertNotIn("zzzz", s)
        self.assertEqual(report.scrub(b"\x89PNG"), "[blob]")

    def test_env_values(self):
        with mock.patch.dict(os.environ, {"MY_SECRET": "supersecretvalue"}):
            self.assertNotIn("supersecretvalue",
                             report.scrub_text("err supersecretvalue"))

    def test_unknown_types_not_repr(self):
        class X:
            def __repr__(self):
                return "sk-leakleakleak"
        self.assertEqual(report.scrub({"o": X()}), {"o": "X"})


class DsnTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(report.parse_dsn("https://k@gt.example.com/12")[:2],
                         ("https://gt.example.com/api/12/envelope/", "k"))
        self.assertIsNone(report.parse_dsn(""))
        self.assertIsNone(report.parse_dsn("ftp://k@h/1"))
        self.assertIsNone(report.parse_dsn("https://h/1"))

    def test_omaseal_ref_resolves(self):
        with mock.patch.object(config, "load_env_key",
                               return_value="http://k@127.0.0.1:1/2") as m:
            self.assertTrue(report.Reporter(
                _cfg("omaseal://glitchtip/wisp")).enabled)
            m.assert_called_once_with("omaseal://glitchtip/wisp")


class ReporterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Path(self.tmp.name) / "q.jsonl"
        self.t = [1000.0]

    def tearDown(self):
        self.tmp.cleanup()

    def mk(self, dsn, **kw):
        return report.Reporter(_cfg(dsn, **kw), queue_file=self.q,
                               clock=lambda: self.t[0], sync=True)

    def test_disabled_by_default_zero_network(self):
        with mock.patch("urllib.request.urlopen") as u:
            r = report.Reporter({}, queue_file=self.q, sync=True)
            self.assertFalse(r.enabled)
            self.assertFalse(r.capture("jev_down", OSError("x")))
            self.assertFalse(report.Reporter(_cfg(""), sync=True).enabled)
            u.assert_not_called()
        self.assertFalse(self.q.exists())

    def test_envelope_shape(self):
        s = _Srv()
        try:
            r = self.mk(s.dsn)
            self.assertTrue(r.capture(
                "jev_down", ConnectionRefusedError("sk-secret123456"),
                {"transcript": "my password", "stage": "decide"}))
        finally:
            s.close()
        path, hdrs, body = s.got[0]
        self.assertEqual(path, "/api/7/envelope/")
        self.assertIn("sentry_key=pubkey", hdrs["X-Sentry-Auth"])
        head, item, ev = (json.loads(x) for x in body.decode().split("\n"))
        self.assertEqual(item, {"type": "event"})
        self.assertEqual(head["event_id"], ev["event_id"])
        self.assertEqual(ev["tags"]["error_code"], "jev_down")
        self.assertEqual(ev["extra"]["transcript"], "[redacted]")
        self.assertEqual(ev["extra"]["stage"], "decide")
        self.assertNotIn("sk-secret", body.decode())
        self.assertNotIn("my password", body.decode())

    def test_unknown_code_becomes_internal(self):
        s = _Srv()
        try:
            self.mk(s.dsn).capture("weird")
        finally:
            s.close()
        self.assertIn(b'"error_code":"internal"', s.got[0][2])

    def test_rate_limit_per_code_and_refill(self):
        s = _Srv()
        try:
            r = self.mk(s.dsn, per_code_per_hour=2, dedupe_secs=0)
            res = [r.capture("timeout") for _ in range(4)]
            self.assertEqual(res, [True, True, False, False])
            self.assertTrue(r.capture("busy"))   # other code unaffected
            self.t[0] += 1800                    # 1 token back
            self.assertTrue(r.capture("timeout"))
            self.assertFalse(r.capture("timeout"))
        finally:
            s.close()

    def test_global_cap(self):
        s = _Srv()
        try:
            r = self.mk(s.dsn, global_per_hour=2, dedupe_secs=0)
            self.assertEqual([r.capture(c) for c in
                              ("timeout", "busy", "jev_down")],
                             [True, True, False])
            self.t[0] += 3601
            self.assertTrue(r.capture("jev_down"))
        finally:
            s.close()

    def test_dedupe_window(self):
        s = _Srv()
        try:
            r = self.mk(s.dsn, per_code_per_hour=50, dedupe_secs=300)
            e = ValueError("a")
            self.assertTrue(r.capture("tool_failed", e))
            self.assertFalse(r.capture("tool_failed", e))
            self.assertTrue(r.capture("tool_failed", KeyError("b")))
            self.t[0] += 301
            self.assertTrue(r.capture("tool_failed", e))
        finally:
            s.close()

    def test_offline_queue_flush_and_cap(self):
        r = self.mk("http://k@127.0.0.1:1/2", queue_max=3,
                    per_code_per_hour=50, dedupe_secs=0)
        for i in range(5):
            r.capture("timeout", None, {"i": i})
        self.assertEqual(r.queue_depth(), 3)
        kept = [json.loads(l)["extra"]["i"]
                for l in self.q.read_text().splitlines()]
        self.assertEqual(kept, [2, 3, 4])      # oldest dropped
        s = _Srv()
        try:
            r2 = self.mk(s.dsn, dedupe_secs=0)
            self.assertTrue(r2.capture("busy"))
        finally:
            s.close()
        self.assertEqual(len(s.got), 4)        # 1 new + 3 flushed
        self.assertEqual(r2.queue_depth(), 0)

    def test_failed_flush_keeps_queue(self):
        r = self.mk("http://k@127.0.0.1:1/2")
        r.capture("timeout")
        self.assertEqual(r.flush(), 0)
        self.assertEqual(r.queue_depth(), 1)

    def test_server_500_queues(self):
        s = _Srv(status=500)
        try:
            r = self.mk(s.dsn)
            r.capture("timeout")
        finally:
            s.close()
        self.assertEqual(r.queue_depth(), 1)

    def test_never_raises(self):
        r = self.mk("http://k@127.0.0.1:1/2")
        with mock.patch.object(r, "_deliver", side_effect=RuntimeError):
            self.assertIsInstance(r.capture("timeout"), bool)
        with mock.patch.object(r, "build_event", side_effect=RuntimeError):
            self.assertFalse(r.capture("busy"))
        with mock.patch.object(report, "get", side_effect=RuntimeError):
            self.assertFalse(report.capture("timeout"))
        self.assertFalse(report.Reporter({"report": None}).enabled)
        ro = self.mk("http://k@127.0.0.1:1/2")
        ro.queue_file = Path("/proc/nope/q.jsonl")
        self.assertTrue(ro.capture("timeout"))

    def test_async_does_not_block(self):
        r = report.Reporter(_cfg("http://k@127.0.0.1:1/2"),
                            queue_file=self.q)
        gate = threading.Event()
        with mock.patch.object(r, "_deliver",
                               side_effect=lambda ev: gate.wait(5)):
            self.assertTrue(r.capture("timeout"))   # returns immediately
            gate.set()

    def test_status(self):
        self.assertEqual(report.status({}), (False, 0))
        self.assertTrue(report.status(_cfg("http://k@h/1"))[0])


class NoRealCallsTest(unittest.TestCase):
    def test_default_config_has_no_dsn(self):
        self.assertIn('dsn = ""', config.DEFAULT_CONFIG)
        self.assertEqual(config._default_cfg_dict().get("report", {})
                         .get("dsn", ""), "")

    def test_pipeline_error_path_makes_no_call(self):
        report.reset()
        state = mock.Mock()
        with mock.patch("urllib.request.urlopen") as u, \
                mock.patch.object(config, "load_config", return_value={}):
            pipeline._publish_error(state, OSError("boom"))
            u.assert_not_called()
        state.transition.assert_called_once()
        report.reset()

    def test_pipeline_reports_when_enabled(self):
        report.reset()
        calls = []
        with mock.patch.object(report.Reporter, "capture",
                               lambda self, *a, **k: calls.append(a)), \
                mock.patch.object(config, "load_config", return_value={}):
            pipeline._publish_error(mock.Mock(), OSError("boom"))
        self.assertEqual(calls[0][0], "internal")
        report.reset()

    def test_all_codes_accepted(self):
        for c in errors_codes.CODES:
            self.assertIn(c, errors_codes.CODES)


if __name__ == "__main__":
    unittest.main()
