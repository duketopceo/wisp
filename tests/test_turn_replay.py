#!/usr/bin/env python3
"""Turn-replay harness tests (backend U14).

Each turn runs the real `wisp.pipeline.run_listen` in a child process
(temp HOME / XDG dirs, fake model servers on 127.0.0.1 ephemeral
ports) and asserts on the observed state events, trace and timings.
No real model server, no paid call, no non-loopback connection.
"""
import copy
import http.client
import json
import pathlib
import socket
import sys
import tempfile
import unittest
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import fakes, runner  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "turns"
FIXTURE_NAMES = ["ask", "act", "choose", "jev_down", "brain_down",
                 "cancel_mid_stream", "stale_choice"]


def _req(url, path, method="GET", body=None):
    host, port = url.replace("http://", "").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    try:
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=data,
                     headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        return r.status, r.read()
    finally:
        conn.close()


class FakeServersTest(unittest.TestCase):
    def test_binds_loopback_ephemeral_and_closes(self):
        srv = fakes.FakeJev({"answers": {}})
        srv.start()
        host, port = srv.server.server_address[:2]
        self.assertEqual(host, "127.0.0.1")
        self.assertGreater(port, 1024)
        self.assertNotIn(port, (8080, 8081, 8091, 8931, 11434))
        srv.stop()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)

    def test_status_and_fail_on_nth_call(self):
        with fakes.FakeJev({"answers": {"route": {"choice": "answer"}},
                            "fail_on_calls": [2],
                            "fail_status": 503}) as srv:
            s1, _ = _req(srv.url, "/x", "POST", {})
            s2, _ = _req(srv.url, "/x", "POST", {})
            s3, _ = _req(srv.url, "/x", "POST", {})
        self.assertEqual((s1, s2, s3), (200, 503, 200))
        self.assertEqual(len(srv.calls), 3)

    def test_latency_is_applied(self):
        import time
        with fakes.FakeJev({"answers": {}, "latency_ms": 150}) as srv:
            t = time.monotonic()
            _req(srv.url, "/x", "POST", {})
            self.assertGreaterEqual(time.monotonic() - t, 0.14)

    def test_brain_sse_stream_chunks(self):
        script = {"responses": [{"chunks": ["Hel", "lo ", "there"]}]}
        with fakes.FakeBrain(script) as srv:
            host, port = srv.server.server_address[:2]
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("POST", "/v1/chat/completions",
                         body=json.dumps({"stream": True,
                                          "messages": []}),
                         headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            self.assertIn("text/event-stream",
                          r.getheader("Content-Type"))
            text = r.read().decode()
            conn.close()
        datas = [l[5:].strip() for l in text.splitlines()
                 if l.startswith("data:")]
        self.assertEqual(datas[-1], "[DONE]")
        pieces = [json.loads(d)["choices"][0]["delta"].get("content", "")
                  for d in datas[:-1]]
        self.assertEqual("".join(pieces), "Hello there")

    def test_brain_non_stream_and_tool_calls(self):
        script = {"responses": [
            {"tool_calls": [{"name": "recall", "arg": "x"}]},
            {"content": "done"}]}
        with fakes.FakeBrain(script) as srv:
            _, b1 = _req(srv.url, "/v1/chat/completions", "POST",
                         {"messages": []})
            _, b2 = _req(srv.url, "/v1/chat/completions", "POST",
                         {"messages": []})
            s, _ = _req(srv.url, "/v1/models")
        m1 = json.loads(b1)["choices"][0]["message"]
        self.assertEqual(m1["tool_calls"][0]["function"]["name"], "recall")
        self.assertEqual(json.loads(b2)["choices"][0]["message"]
                         ["content"], "done")
        self.assertEqual(s, 200)

    def test_whisper_both_endpoints(self):
        with fakes.FakeWhisper({"transcript": "hello world"}) as srv:
            _, a = _req(srv.url, "/audio/transcriptions", "POST", {})
            _, b = _req(srv.url, "/inference", "POST", {})
        self.assertEqual(json.loads(a)["text"], "hello world")
        self.assertEqual(json.loads(b)["text"], "hello world")

    def test_uitars_and_batch(self):
        with fakes.FakeUiTars({"responses": [
                {"content": "click(start_box='(10,20)')"}]}) as srv:
            _, b = _req(srv.url, "/v1/chat/completions", "POST",
                        {"messages": []})
        self.assertIn("click", json.loads(b)["choices"][0]["message"]
                      ["content"])
        with fakes.FakeBatch({"statuses": ["in_progress", "completed"],
                              "results": [{"custom_id": "a",
                                           "content": "ok"}]}) as srv:
            _, sub = _req(srv.url, "/batches", "POST", {"requests": []})
            bid = json.loads(sub)["id"]
            _, p1 = _req(srv.url, f"/batches/{bid}")
            _, p2 = _req(srv.url, f"/batches/{bid}")
        self.assertEqual(json.loads(p1)["status"], "in_progress")
        self.assertEqual(json.loads(p2)["status"], "completed")


class GuardTest(unittest.TestCase):
    def test_guard_blocks_non_loopback_and_allows_loopback(self):
        guard = runner.NetworkGuard()
        guard.install()
        try:
            with self.assertRaises(runner.NetworkViolation):
                socket.create_connection(("192.0.2.1", 80), timeout=1)
            with self.assertRaises(runner.NetworkViolation):
                socket.getaddrinfo("example.com", 443)
            with fakes.FakeJev({"answers": {}}) as srv:
                status, _ = _req(srv.url, "/x", "POST", {})
                self.assertEqual(status, 200)
        finally:
            guard.uninstall()
        self.assertTrue(any("192.0.2.1" in v for v in guard.violations))
        # uninstalled: the real socket class is back
        self.assertNotIn("Guard", socket.socket.connect.__qualname__)

    def test_turn_that_dials_out_is_blocked_and_reported(self):
        fx = runner.load_fixture(FIXTURES / "ask.json")
        fx = copy.deepcopy(fx)
        # point the brain at a TEST-NET address: the guard must stop it
        fx["brain_base_url_override"] = "http://192.0.2.1:9/v1"
        res = runner.run_turn(fx)
        self.assertTrue(res.violations, "guard recorded no violation")
        self.assertTrue(any("192.0.2.1" in v for v in res.violations))


class FixtureFilesTest(unittest.TestCase):
    def test_all_named_fixtures_exist_and_parse(self):
        for name in FIXTURE_NAMES:
            with self.subTest(name):
                fx = runner.load_fixture(FIXTURES / f"{name}.json")
                self.assertEqual(fx["name"], name)
                self.assertIn("expect", fx)

    def test_wavs_are_tiny_synthetic_valid(self):
        wavs = sorted(FIXTURES.glob("*.wav"))
        self.assertTrue(wavs)
        for p in wavs:
            with self.subTest(p.name):
                self.assertLess(p.stat().st_size, 200_000)
                with wave.open(str(p)) as w:
                    self.assertEqual(w.getnchannels(), 1)
                    self.assertEqual(w.getframerate(), 16000)
                    self.assertGreater(w.getnframes(), 1000)


class TurnReplayTest(unittest.TestCase):
    def test_ask_event_sequence_and_answer(self):
        res = runner.run_turn(FIXTURES / "ask.json")
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.assertEqual(res.statuses,
                         ["listening", "transcribing", "deciding",
                          "acting", "speaking", "done"])
        self.assertEqual(res.final["transcript"], "what time is it")
        self.assertEqual(res.final["answer"], "It is half past three.")
        self.assertEqual(res.violations, [])
        # one call per fake
        self.assertEqual(len(res.calls["whisper"]), 1)
        self.assertEqual(len(res.calls["jev"]), 1)
        self.assertEqual(len(res.chat_calls()), 1)

    def test_scripted_brain_latency_shows_in_first_token_span(self):
        fx = copy.deepcopy(runner.load_fixture(FIXTURES / "ask.json"))
        fx["endpoints"]["brain"]["responses"][0]["latency_ms"] = 300
        res = runner.run_turn(fx)
        self.assertEqual(res.exit_code, 0, res.stderr)
        ft = res.spans["first_token_ms"]
        self.assertAlmostEqual(ft, 300, delta=50)

    def test_every_fixture_meets_its_expectations(self):
        for name in FIXTURE_NAMES:
            with self.subTest(name):
                res = runner.run_turn(FIXTURES / f"{name}.json")
                self.assertEqual(res.violations, [])
                problems = runner.check_expectations(res)
                self.assertEqual(problems, [], f"{name}: {problems}")

    def test_act_runs_two_tool_steps(self):
        res = runner.run_turn(FIXTURES / "act.json")
        self.assertEqual(len(res.chat_calls()), 3)
        tool_names = [t["name"] for t in res.trace_events("tool_call")]
        self.assertEqual(tool_names, ["recall", "recall"])
        self.assertTrue(res.final["result"].startswith("ACTED (2 steps)"))

    def test_choose_offers_choices_then_launches_pick(self):
        res = runner.run_turn(FIXTURES / "choose.json")
        self.assertIn("awaiting_choice", res.statuses)
        offered = [e["choices"] for e in res.events
                   if e["status"] == "awaiting_choice"][0]
        self.assertIn("app:discord", offered)
        self.assertEqual(res.launch_calls, ["discord"])

    def test_choice_timeout_auto_picks_top_candidate(self):
        fx = copy.deepcopy(runner.load_fixture(FIXTURES / "choose.json"))
        fx["chooser"] = {"pick": None}
        res = runner.run_turn(fx)
        self.assertEqual(res.launch_calls, ["discord"])

    def test_stale_choice_baseline_is_accepted_verbatim(self):
        # characterization: a pick that was never offered is applied
        res = runner.run_turn(FIXTURES / "stale_choice.json")
        self.assertEqual(res.launch_calls, ["ghostapp"])

    def test_jev_down_baseline_is_error_state(self):
        # characterization: no fallback router yet (U8 changes this)
        res = runner.run_turn(FIXTURES / "jev_down.json")
        self.assertEqual(res.statuses[-1], "error")
        self.assertIn("Jev HTTP 503", res.final["error"])

    def test_brain_down_baseline_falls_back_to_canned_answer(self):
        res = runner.run_turn(FIXTURES / "brain_down.json")
        self.assertIn("ANSWER_FAILED", res.final["result"])
        self.assertEqual(res.statuses[-1], "done")

    def test_cancel_mid_stream_baseline_ignored_for_answer_route(self):
        # characterization: interrupted() is only honoured by the act
        # loop today; U9 makes the answer stream cancellable
        res = runner.run_turn(FIXTURES / "cancel_mid_stream.json")
        self.assertTrue(res.interrupt_fired)
        self.assertEqual(res.statuses[-1], "done")
        self.assertTrue(res.final["answer"])

    def test_act_loop_honours_cancel_between_steps(self):
        fx = copy.deepcopy(runner.load_fixture(FIXTURES / "act.json"))
        for r in fx["endpoints"]["brain"]["responses"]:
            r["latency_ms"] = 200
        fx["interrupt_after_ms"] = 100
        res = runner.run_turn(fx)
        self.assertTrue(res.final["result"].startswith("INTERRUPTED"))

    def test_cleanup_removes_tempdir_and_ports(self):
        res = runner.run_turn(FIXTURES / "ask.json")
        self.assertFalse(pathlib.Path(res.tempdir).exists())
        for url in res.endpoint_urls.values():
            host, port = url.replace("http://", "").split(":")
            with self.assertRaises(OSError):
                socket.create_connection((host, int(port)), timeout=1)

    def test_never_touches_live_service_ports(self):
        res = runner.run_turn(FIXTURES / "ask.json")
        live = {8080, 8081, 8091, 8931, 11434}
        for url in res.endpoint_urls.values():
            self.assertNotIn(int(url.rsplit(":", 1)[1]), live)


class ReplayScriptTest(unittest.TestCase):
    def test_script_prints_timeline(self):
        import subprocess
        out = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "replay_turn.py"),
             str(FIXTURES / "ask.json")],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("listening", out.stdout)
        self.assertIn("speaking", out.stdout)
        self.assertIn("It is half past three.", out.stdout)


if __name__ == "__main__":
    unittest.main()
