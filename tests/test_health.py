#!/usr/bin/env python3
"""Endpoint health, typed error codes and the brain fallback chain
(backend U7). Only loopback fakes from tests/harness are used — no live
service, no paid call, no systemctl."""
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import fakes  # noqa: E402
from wisp import (brain, config, errors_codes, health,  # noqa: E402
                  pipeline, state as state_mod, trace)

ASK = [{"role": "user", "content": "hi"}]


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def brain_cfg(primary, fallback=(), **extra):
    """cfg with provider sections named p0, p1, ... pointing at URLs."""
    cfg = {"brain": {"default": "p0:m0"}}
    for i, url in enumerate([primary, *fallback]):
        cfg[f"brain.p{i}"] = {"kind": "openai_compat",
                              "base_url": url + "/v1", "key_env": "",
                              "vision": "false", "tools": "true"}
    if fallback:
        cfg["brain"]["fallback"] = ",".join(
            f"p{i + 1}:m{i + 1}" for i in range(len(fallback)))
    cfg["brain"].update(extra.pop("brain", {}))
    cfg.update(extra)
    return cfg


class ErrorCodesTest(unittest.TestCase):
    def test_closed_code_set(self):
        self.assertEqual(set(errors_codes.CODES), {
            "jev_down", "brain_down", "stt_down", "ground_down",
            "ground_failed", "timeout", "cancelled", "busy",
            "stale_prompt", "restarted", "tool_failed",
            "budget_exceeded", "internal"})

    def test_every_code_has_human_safe_copy(self):
        for c in errors_codes.CODES:
            msg = errors_codes.human(c)
            self.assertTrue(msg)
            self.assertNotIn("Traceback", msg)

    def test_wisp_error_keeps_raw_detail_out_of_public(self):
        e = errors_codes.WispError("jev_down", "Jev HTTP 503: secret body")
        self.assertEqual(e.code, "jev_down")
        self.assertNotIn("secret", e.public)
        self.assertIn("Jev HTTP 503", e.detail)
        self.assertIsInstance(e, RuntimeError)
        self.assertIn("Jev HTTP 503", str(e))

    def test_unknown_code_rejected(self):
        with self.assertRaises(ValueError):
            errors_codes.WispError("nope")

    def test_classify_mapping(self):
        c = errors_codes.classify
        refused = urllib.error.URLError(ConnectionRefusedError(111, "no"))
        self.assertEqual(c(refused, "brain_down").code, "brain_down")
        self.assertEqual(c(ConnectionResetError(), "jev_down").code,
                         "jev_down")
        self.assertEqual(c(socket.timeout("t"), "brain_down").code,
                         "timeout")
        self.assertEqual(c(TimeoutError(), "jev_down").code, "timeout")
        http5 = urllib.error.HTTPError("u", 503, "x", {}, None)
        self.assertEqual(c(http5, "stt_down").code, "stt_down")
        self.assertEqual(c(json.JSONDecodeError("x", "y", 0),
                           "brain_down").code, "brain_down")
        self.assertEqual(c(KeyError("k"), "brain_down").code, "internal")
        keep = errors_codes.WispError("busy")
        self.assertIs(c(keep, "brain_down"), keep)

    def test_is_connection_failure(self):
        f = errors_codes.is_connection_failure
        self.assertTrue(f(urllib.error.URLError(
            ConnectionRefusedError())))
        self.assertTrue(f(ConnectionResetError()))
        self.assertTrue(f(urllib.error.URLError(ConnectionResetError())))
        self.assertFalse(f(socket.timeout()))
        self.assertFalse(f(urllib.error.URLError(socket.timeout())))
        self.assertFalse(f(urllib.error.HTTPError("u", 500, "x", {}, None)))


class HealthBase(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        p = mock.patch.object(trace, "TRACE_FILE", self.td / "t.jsonl")
        p.start()
        self.addCleanup(p.stop)
        self.stack = []

    def fake(self, kind, script=None):
        f = fakes.KINDS[kind](script or {}).start()
        self.addCleanup(f.stop)
        return f

    def bus(self):
        b = state_mod.StateBus(state_file=self.td / "state.json",
                               autostart=False)
        self.addCleanup(b.close)
        return b


class RegistryTest(HealthBase):
    def test_all_up_reports_ok_with_latency(self):
        jev, b0, b1 = self.fake("jev"), self.fake("brain"), \
            self.fake("brain")
        cfg = brain_cfg(b0.url, [b1.url])
        reg = health.HealthRegistry(cfg, jev_url=jev.url + "/api/x")
        reg.probe_all()
        snap = reg.snapshot()
        self.assertEqual(set(snap), {"jev", "brain_p0", "brain_p1"})
        for name, row in snap.items():
            self.assertTrue(row["ok"], name)
            self.assertIsNone(row["code"])
            self.assertIsInstance(row["latency_ms"], int)
            self.assertIn("since", row)

    def test_probe_calls_are_not_counted_as_completions(self):
        b0 = self.fake("brain")
        reg = health.HealthRegistry(brain_cfg(b0.url), jev_url="")
        reg.probe_all()
        self.assertEqual(
            [c for c in b0.calls
             if c["path"].endswith("/chat/completions")], [])
        self.assertTrue(b0.calls)  # but the probe did reach it

    def test_stopped_jev_flips_once_and_fires_one_event(self):
        jev = self.fake("jev")
        bus = self.bus()
        sub = bus.subscribe()
        reg = health.HealthRegistry({}, bus=bus,
                                    jev_url=jev.url + "/api/x")
        reg.probe_all()
        self.assertTrue(bus.snapshot()["health"]["jev"]["ok"])
        jev.stop()
        reg.probe_all()
        reg.probe_all()
        row = bus.snapshot()["health"]["jev"]
        self.assertFalse(row["ok"])
        self.assertEqual(row["code"], "jev_down")
        events = []
        while True:
            ev = sub.get(0.05)
            if ev is None:
                break
            if ev.get("name") == "health_changed":
                events.append(ev)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "event")
        self.assertEqual(events[0]["data"]["name"], "jev")
        self.assertFalse(events[0]["data"]["ok"])
        self.assertEqual(events[0]["data"]["code"], "jev_down")

    def test_recovery_fires_a_second_event(self):
        port = closed_port()
        bus = self.bus()
        sub = bus.subscribe()
        reg = health.HealthRegistry({}, bus=bus,
                                    jev_url=f"http://127.0.0.1:{port}/x")
        reg.probe_all()  # first observation: down -> event
        self.assertFalse(bus.snapshot()["health"]["jev"]["ok"])
        # bring something up on that port
        srv = fakes.FakeJev({})
        srv.server.server_close()
        from http.server import ThreadingHTTPServer
        srv.server = ThreadingHTTPServer(("127.0.0.1", port),
                                         fakes._Handler)
        srv.server.daemon_threads = True
        srv.server.fake = srv
        srv.start()
        self.addCleanup(srv.stop)
        reg.probe_all()
        self.assertTrue(bus.snapshot()["health"]["jev"]["ok"])
        names = []
        while (ev := sub.get(0.05)) is not None:
            if ev.get("name") == "health_changed":
                names.append(ev["data"]["ok"])
        self.assertEqual(names, [False, True])

    def test_hook_registered_probe_included(self):
        # U5's hypr.health() shape; wisp/hypr.py is not imported here
        reg = health.HealthRegistry({}, jev_url="")
        reg.register("hypr", lambda: {"ok": False,
                                      "code": "hypr_unavailable"})
        reg.probe_all()
        row = reg.snapshot()["hypr"]
        self.assertFalse(row["ok"])
        self.assertEqual(row["code"], "hypr_unavailable")

    def test_hook_that_raises_is_down_not_fatal(self):
        reg = health.HealthRegistry({}, jev_url="")

        def boom():
            raise RuntimeError("x")
        reg.register("odd", boom)
        reg.probe_all()
        self.assertFalse(reg.snapshot()["odd"]["ok"])

    def test_remote_endpoints_are_never_probed(self):
        reg = health.HealthRegistry(
            {"brain": {"default": "openrouter:x"}},
            jev_url="https://openrouter.ai/api/alpha/decisions")
        with mock.patch("urllib.request.urlopen") as uo:
            reg.probe_all()
        uo.assert_not_called()
        self.assertEqual(reg.snapshot(), {})

    def test_on_press_probes_only_when_stale(self):
        jev = self.fake("jev")
        now = [100.0]
        reg = health.HealthRegistry({}, jev_url=jev.url + "/x",
                                    clock=lambda: now[0])
        reg.on_press()
        n1 = len(jev.calls)
        self.assertGreaterEqual(n1, 1)
        now[0] += 5          # fresher than 10 s: no new probe
        reg.on_press()
        self.assertEqual(len(jev.calls), n1)
        now[0] += 6          # now 11 s old
        reg.on_press()
        self.assertGreater(len(jev.calls), n1)

    def test_known_down_requires_a_recent_down_observation(self):
        now = [0.0]
        reg = health.HealthRegistry({}, jev_url="", clock=lambda: now[0])
        reg.register("x", lambda: {"ok": False, "code": "jev_down"})
        reg.probe_all()
        self.assertTrue(reg.known_down("x"))
        now[0] += 11
        self.assertFalse(reg.known_down("x"))      # stale: unknown
        self.assertFalse(reg.known_down("never_seen"))

    def test_report_failure_marks_down_and_reprobes(self):
        jev = self.fake("jev")
        reg = health.HealthRegistry({}, jev_url=jev.url + "/x")
        reg.probe_all()
        n = len(jev.calls)
        reg.report_failure("jev", "jev_down")
        self.assertGreater(len(jev.calls), n)      # immediate re-probe
        self.assertTrue(reg.snapshot()["jev"]["ok"])  # it is actually up

    def test_probe_timeout_is_500ms(self):
        jev = self.fake("jev", {"latency_ms": 2000})
        # latency applies to counted calls only; probes answer at once,
        # so use a socket that accepts and never answers
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        self.addCleanup(srv.close)
        reg = health.HealthRegistry(
            {}, jev_url=f"http://127.0.0.1:{srv.getsockname()[1]}/x")
        t = time.monotonic()
        reg.probe_all()
        self.assertLess(time.monotonic() - t, 1.5)
        row = reg.snapshot()["jev"]
        self.assertFalse(row["ok"])
        self.assertEqual(row["code"], "timeout")

    def test_background_loop_probes_on_interval_and_stops(self):
        jev = self.fake("jev")
        reg = health.HealthRegistry({"health": {"interval_s": "0.05"}},
                                    jev_url=jev.url + "/x")
        reg.start()
        time.sleep(0.4)
        reg.stop()
        n = len(jev.calls)
        self.assertGreaterEqual(n, 3)
        time.sleep(0.2)
        self.assertEqual(len(jev.calls), n)

    def test_health_config_keys(self):
        cfg = {"health": {"interval_s": "7", "press_stale_s": "3",
                          "timeout_ms": "250", "uitars": "http://127.0.0.1:1",
                          "ollama": "http://127.0.0.1:2"}}
        reg = health.HealthRegistry(cfg, jev_url="")
        self.assertEqual(reg.interval_s, 7.0)
        self.assertEqual(reg.press_stale_s, 3.0)
        self.assertEqual(reg.timeout_s, 0.25)
        names = {e.name for e in health.endpoints(cfg, jev_url="")}
        self.assertEqual(names, {"uitars", "ollama"})

    def test_stt_endpoint_only_for_loopback_openai_provider(self):
        w = self.fake("whisper", {"transcript": "x"})
        cfg = {"stt": {"provider": "openai", "base_url": w.url}}
        reg = health.HealthRegistry(cfg, jev_url="")
        reg.probe_all()
        self.assertTrue(reg.snapshot()["stt"]["ok"])
        self.assertEqual(
            health.endpoints({"stt": {"provider": "local"}}, jev_url=""),
            [])


class UnitsTest(unittest.TestCase):
    def test_units_to_start_lists_only_down_endpoints(self):
        cfg = {"health.units": {"jev": "llama-jev,jev-shim",
                                "brain_p0": "llama-local",
                                "uitars": "llama-uitars"}}
        snap = {"jev": {"ok": False}, "brain_p0": {"ok": True},
                "uitars": {"ok": False}}
        self.assertEqual(health.units_to_start(cfg, snap),
                         ["llama-jev.service", "jev-shim.service",
                          "llama-uitars.service"])

    def test_nothing_down_nothing_to_start(self):
        self.assertEqual(health.units_to_start(
            {"health.units": {"jev": "jev-shim"}},
            {"jev": {"ok": True}}), [])

    def test_start_commands_are_user_scope_systemctl(self):
        self.assertEqual(
            health.start_command(["a.service", "b.service"]),
            ["systemctl", "--user", "start", "a.service", "b.service"])


class JevTest(HealthBase):
    def _no_key(self):
        env = {k: v for k, v in os.environ.items()
               if k != "OPENROUTER_API_KEY"}
        for p in (mock.patch.dict(os.environ, env, clear=True),
                  mock.patch.object(config, "ENV_FILE",
                                    self.td / "no.env")):
            p.start()
            self.addCleanup(p.stop)

    def test_local_endpoint_needs_no_api_key(self):
        self._no_key()
        jev = self.fake("jev", {"answers": {"route": {"choice": "answer"}}})
        with mock.patch.object(config, "JEV_ENDPOINT",
                               jev.url + "/api/alpha/decisions"):
            out = pipeline.ask_jev("hi", "m", {})
        self.assertEqual(out["answers"]["route"]["choice"], "answer")
        # no Authorization header was needed or sent as "Bearer "+""
        self.assertEqual(len(jev.calls), 1)

    def test_remote_endpoint_without_key_is_a_coded_error(self):
        self._no_key()
        with mock.patch.object(config, "JEV_ENDPOINT",
                               "https://openrouter.ai/api/alpha/decisions"):
            with self.assertRaises(errors_codes.WispError) as cm:
                pipeline.ask_jev("hi", "m", {})
        self.assertEqual(cm.exception.code, "jev_down")
        self.assertIn("OPENROUTER_API_KEY", cm.exception.detail)

    def test_http_503_is_jev_down_with_raw_detail(self):
        jev = self.fake("jev", {"status": 503})
        with mock.patch.object(config, "JEV_ENDPOINT",
                               jev.url + "/api/alpha/decisions"):
            with self.assertRaises(errors_codes.WispError) as cm:
                pipeline.ask_jev("hi", "m", {})
        self.assertEqual(cm.exception.code, "jev_down")
        self.assertIn("Jev HTTP 503", cm.exception.detail)
        self.assertNotIn("503", cm.exception.public)
        self.assertEqual(len(jev.calls), 1)        # 5xx: no retry

    def test_refused_retries_once_then_jev_down(self):
        port = closed_port()
        calls = []
        real = pipeline.urllib.request.urlopen

        def spy(*a, **k):
            calls.append(1)
            return real(*a, **k)
        with mock.patch.object(config, "JEV_ENDPOINT",
                               f"http://127.0.0.1:{port}/x"), \
                mock.patch.object(pipeline.urllib.request, "urlopen", spy):
            with self.assertRaises(errors_codes.WispError) as cm:
                pipeline.ask_jev("hi", "m", {})
        self.assertEqual(cm.exception.code, "jev_down")
        self.assertEqual(len(calls), 2)

    def test_reset_once_then_success(self):
        jev = self.fake("jev", {"drop_on_calls": [1],
                                "answers": {"route": {"choice": "answer"}}})
        with mock.patch.object(config, "JEV_ENDPOINT",
                               jev.url + "/api/alpha/decisions"):
            out = pipeline.ask_jev("hi", "m", {})
        self.assertIn("answers", out)
        self.assertEqual(len(jev.calls), 2)

    def test_timeout_is_not_retried_and_coded_timeout(self):
        calls = []

        def slow(*a, **k):
            calls.append(1)
            raise socket.timeout("timed out")
        with mock.patch.object(pipeline.urllib.request, "urlopen", slow), \
                mock.patch.object(config, "JEV_ENDPOINT",
                                  "http://127.0.0.1:9/x"):
            with self.assertRaises(errors_codes.WispError) as cm:
                pipeline.ask_jev("hi", "m", {})
        self.assertEqual(cm.exception.code, "timeout")
        self.assertEqual(len(calls), 1)

    def test_bad_json_is_jev_down(self):
        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return b"<html>"
        with mock.patch.object(pipeline.urllib.request, "urlopen",
                               return_value=R()), \
                mock.patch.object(config, "JEV_ENDPOINT",
                                  "http://127.0.0.1:9/x"):
            with self.assertRaises(errors_codes.WispError) as cm:
                pipeline.ask_jev("hi", "m", {})
        self.assertEqual(cm.exception.code, "jev_down")


class ChainTest(HealthBase):
    def test_chain_order_and_paid_flag(self):
        cfg = {"brain": {"default": "p0:a",
                         "fallback": "p1:b, openrouter:cheap/x"},
               "brain.p0": {"base_url": "http://127.0.0.1:1/v1"},
               "brain.p1": {"base_url": "http://127.0.0.1:2/v1"}}
        ch = brain.chain(cfg)
        self.assertEqual([(p["name"], p["model"]) for p in ch],
                         [("p0", "a"), ("p1", "b"),
                          ("openrouter", "cheap/x")])
        self.assertEqual([p["paid"] for p in ch], [False, False, True])

    def test_no_fallback_key_is_single_entry(self):
        self.assertEqual(len(brain.chain({"brain": {"default": "mlx:m"}})),
                         1)

    def test_fallback_answers_when_primary_refused(self):
        b1 = self.fake("brain", {"responses": [{"content": "from two"}]})
        cfg = brain_cfg(f"http://127.0.0.1:{closed_port()}", [b1.url])
        got = []
        out = brain.chat_stream(ASK, cfg, on_delta=got.append, timeout=5)
        self.assertEqual(out["content"], "from two")
        self.assertEqual(out["provider"], "p1")
        self.assertEqual(out["fallback_from"], "p0")
        self.assertTrue(got)
        events = [e for e in trace.read(tail=50)
                  if e["step"] == "brain_fallback"]
        self.assertEqual(events[0]["data"]["fallback_from"], "p0")
        self.assertEqual(events[0]["data"]["to"], "p1")

    def test_primary_answer_has_no_fallback_from(self):
        b0 = self.fake("brain", {"responses": [{"content": "one"}]})
        out = brain.chat_stream(ASK, brain_cfg(b0.url), timeout=5)
        self.assertEqual(out["content"], "one")
        self.assertIsNone(out["fallback_from"])

    def test_chat_non_stream_also_falls_back(self):
        b1 = self.fake("brain", {"responses": [{"content": "two"}]})
        cfg = brain_cfg(f"http://127.0.0.1:{closed_port()}", [b1.url])
        out = brain.chat(ASK, cfg, timeout=5)
        self.assertEqual(out["content"], "two")
        self.assertEqual(out["fallback_from"], "p0")

    def test_all_entries_down_is_brain_down_fast(self):
        cfg = brain_cfg(f"http://127.0.0.1:{closed_port()}",
                        [f"http://127.0.0.1:{closed_port()}"])
        t = time.monotonic()
        with self.assertRaises(errors_codes.WispError) as cm:
            brain.chat_stream(ASK, cfg, timeout=5)
        self.assertLess(time.monotonic() - t, 1.0)
        self.assertEqual(cm.exception.code, "brain_down")
        self.assertIn("p0", cm.exception.detail)
        self.assertIn("p1", cm.exception.detail)

    def test_reset_once_retries_once_then_answers(self):
        b0 = self.fake("brain", {"drop_on_calls": [1],
                                 "responses": [{"content": "ok now"}]})
        out = brain.chat_stream(ASK, brain_cfg(b0.url), timeout=5)
        self.assertEqual(out["content"], "ok now")
        self.assertIsNone(out["fallback_from"])
        n = [c for c in b0.calls
             if c["path"].endswith("/chat/completions")]
        self.assertEqual(len(n), 2)

    def test_reset_twice_moves_on(self):
        b0 = self.fake("brain", {"drop_on_calls": [1, 2, 3]})
        b1 = self.fake("brain", {"responses": [{"content": "two"}]})
        out = brain.chat_stream(ASK, brain_cfg(b0.url, [b1.url]),
                                timeout=5)
        self.assertEqual(out["content"], "two")
        n = [c for c in b0.calls
             if c["path"].endswith("/chat/completions")]
        self.assertEqual(len(n), 2)               # one retry, no more

    def test_timeout_is_not_retried(self):
        b0 = self.fake("brain", {"responses": [{"content": "late",
                                                "latency_ms": 1500}]})
        cfg = brain_cfg(b0.url)
        t = time.monotonic()
        with self.assertRaises(errors_codes.WispError) as cm:
            brain.chat(ASK, cfg, timeout=0.3)
        self.assertLess(time.monotonic() - t, 1.2)
        self.assertEqual(cm.exception.code, "brain_down")
        self.assertEqual(len([c for c in b0.calls if c["path"].endswith(
            "/chat/completions")]), 1)

    def test_first_token_deadline_moves_to_next_entry(self):
        slow = self.fake("brain", {"responses": [{
            "content": "cold model", "latency_ms": 2000}]})
        fast = self.fake("brain", {"responses": [{"content": "warm"}]})
        cfg = brain_cfg(slow.url, [fast.url],
                        brain={"first_token_s": "0.3"})
        t = time.monotonic()
        out = brain.chat_stream(ASK, cfg, timeout=10)
        self.assertLess(time.monotonic() - t, 1.5)
        self.assertEqual(out["content"], "warm")
        self.assertEqual(out["fallback_from"], "p0")

    def test_first_token_deadline_single_entry_is_brain_down(self):
        slow = self.fake("brain", {"responses": [{
            "chunks": ["a"], "latency_ms": 2000}]})
        cfg = brain_cfg(slow.url, brain={"first_token_s": "0.3"})
        t = time.monotonic()
        with self.assertRaises(errors_codes.WispError) as cm:
            brain.chat_stream(ASK, cfg, timeout=10)
        self.assertLess(time.monotonic() - t, 1.5)
        self.assertEqual(cm.exception.code, "brain_down")

    def test_slow_stream_after_first_token_is_not_cut_off(self):
        b0 = self.fake("brain", {"responses": [{
            "chunks": ["a ", "b ", "c"], "chunk_delay_ms": 150}]})
        cfg = brain_cfg(b0.url, brain={"first_token_s": "0.4"})
        out = brain.chat_stream(ASK, cfg, timeout=10)
        self.assertEqual(out["content"], "a b c")

    def test_paid_entry_disabled_is_never_called(self):
        paid = self.fake("brain", {"responses": [{"content": "paid"}]})
        cfg = brain_cfg(f"http://127.0.0.1:{closed_port()}", [paid.url])
        cfg["brain.p1"]["paid"] = "true"
        with self.assertRaises(errors_codes.WispError) as cm:
            brain.chat_stream(ASK, cfg, timeout=5)
        self.assertEqual(cm.exception.code, "brain_down")
        self.assertEqual(paid.calls, [])

    def test_paid_entry_enabled_is_used(self):
        paid = self.fake("brain", {"responses": [{"content": "paid"}]})
        cfg = brain_cfg(f"http://127.0.0.1:{closed_port()}", [paid.url],
                        brain={"allow_paid": "true"})
        cfg["brain.p1"]["paid"] = "true"
        out = brain.chat_stream(ASK, cfg, timeout=5)
        self.assertEqual(out["content"], "paid")

    def test_paid_entry_over_budget_hook_is_skipped(self):
        paid = self.fake("brain", {"responses": [{"content": "paid"}]})
        cfg = brain_cfg(f"http://127.0.0.1:{closed_port()}", [paid.url],
                        brain={"allow_paid": "true"})
        cfg["brain.p1"]["paid"] = "true"
        with mock.patch.object(brain, "budget_ok", return_value=False):
            with self.assertRaises(errors_codes.WispError):
                brain.chat_stream(ASK, cfg, timeout=5)
        self.assertEqual(paid.calls, [])

    def test_openrouter_entry_counts_as_paid_by_default(self):
        cfg = {"brain": {"default": "p0:a",
                         "fallback": "openrouter:cheap/x"},
               "brain.p0": {"base_url":
                            f"http://127.0.0.1:{closed_port()}/v1"}}
        with mock.patch.object(brain.urllib.request, "urlopen",
                               side_effect=ConnectionRefusedError()) as uo:
            with self.assertRaises(errors_codes.WispError):
                brain.chat(ASK, cfg, timeout=5)
        urls = [c.args[0].full_url for c in uo.call_args_list]
        self.assertFalse(any("openrouter.ai" in u for u in urls))

    def test_entry_known_down_is_skipped_without_a_call(self):
        b0 = self.fake("brain", {"responses": [{"content": "zero"}]})
        b1 = self.fake("brain", {"responses": [{"content": "one"}]})
        reg = health.HealthRegistry({}, jev_url="")
        reg.register("brain_p0", lambda: {"ok": False,
                                          "code": "brain_down"})
        reg.probe_all()
        with mock.patch.object(brain, "HEALTH", reg):
            out = brain.chat_stream(ASK, brain_cfg(b0.url, [b1.url]),
                                    timeout=5)
        self.assertEqual(out["content"], "one")
        self.assertEqual(b0.calls, [])

    def test_tool_calls_skip_entries_without_tool_support(self):
        b0 = self.fake("brain", {"responses": [{"content": "x"}]})
        cfg = brain_cfg(f"http://127.0.0.1:{closed_port()}", [b0.url])
        cfg["brain.p1"]["tools"] = "false"
        with self.assertRaises(errors_codes.WispError):
            brain.chat(ASK, cfg, tools=[{"type": "function"}], timeout=5)
        self.assertEqual(b0.calls, [])

    def test_ollama_native_stream_and_first_token(self):
        # ollama kind streams NDJSON from /api/chat
        lines = [json.dumps({"message": {"content": c}, "done": False})
                 for c in ("Hel", "lo")] + \
                [json.dumps({"message": {"content": ""}, "done": True})]
        body = ("\n".join(lines) + "\n").encode()

        class Resp:
            def __enter__(s): return iter(body.splitlines(keepends=True))
            def __exit__(s, *a): return False
        seen = {}

        def fake(req, timeout=None):
            seen["body"] = json.loads(req.data)
            return Resp()
        got = []
        cfg = {"brain": {"default": "ollama:m"}}
        with mock.patch.object(brain.urllib.request, "urlopen", fake):
            out = brain.chat_stream(ASK, cfg, on_delta=got.append)
        self.assertTrue(seen["body"]["stream"])
        self.assertEqual(out["content"], "Hello")
        self.assertEqual(got, ["Hel", "Hello"])


class TurnErrorCodesTest(HealthBase):
    """The bus carries error_code / error_detail; error is human-safe."""

    def test_state_has_typed_error_fields(self):
        bus = self.bus()
        t = bus.begin_turn()
        bus.publish(t, status="error", error="Jev is offline",
                    error_code="jev_down", error_detail="Jev HTTP 503: x")
        s = bus.snapshot()
        self.assertEqual(s["error_code"], "jev_down")
        self.assertEqual(s["error_detail"], "Jev HTTP 503: x")
        self.assertEqual(s["health"], {})

    def test_new_turn_listening_clears_error_code(self):
        bus = self.bus()
        t = bus.begin_turn()
        bus.publish(t, status="error", error="x", error_code="brain_down",
                    error_detail="d")
        t2 = bus.begin_turn()
        bus.publish(t2, status="listening", error="", error_code="",
                    error_detail="")
        self.assertEqual(bus.snapshot()["error_code"], "")

    def test_pipeline_error_path_publishes_codes(self):
        bus = self.bus()
        turn = bus.begin_turn()
        ts = bus.turn(turn)
        err = errors_codes.WispError("brain_down", "p0 refused")
        pipeline._publish_error(ts, err)
        s = bus.snapshot()
        self.assertEqual(s["status"], "error")
        self.assertEqual(s["error_code"], "brain_down")
        self.assertEqual(s["error"], errors_codes.human("brain_down"))
        self.assertEqual(s["error_detail"], "p0 refused")

    def test_unclassified_exception_becomes_internal(self):
        bus = self.bus()
        ts = bus.turn(bus.begin_turn())
        pipeline._publish_error(ts, ValueError("boom /home/x"))
        s = bus.snapshot()
        self.assertEqual(s["error_code"], "internal")
        self.assertNotIn("boom", s["error"])
        self.assertIn("boom", s["error_detail"])


class WispdModelsTest(unittest.TestCase):
    """`wispd models start` prints by default and never runs systemctl
    unless --run is given. Here --run is never passed."""

    def _run(self, *args, endpoint):
        td = tempfile.mkdtemp()
        cfgdir = pathlib.Path(td) / ".config" / "wisp"
        cfgdir.mkdir(parents=True)
        (cfgdir / "config.toml").write_text(
            "[brain]\nrouter = \"jev\"\ndefault = \"openrouter:x\"\n"
            "[health.units]\njev = \"llama-jev,jev-shim\"\n")
        env = {"PATH": os.environ.get("PATH", ""), "HOME": td,
               "XDG_CONFIG_HOME": str(pathlib.Path(td) / "config"),
               "XDG_DATA_HOME": str(pathlib.Path(td) / "data"),
               "XDG_STATE_HOME": str(pathlib.Path(td) / "state"),
               "XDG_RUNTIME_DIR": td, "WISP_OS": "linux",
               "WISP_JEV_ENDPOINT": endpoint}
        return subprocess.run([sys.executable, str(ROOT / "wispd"), *args],
                              env=env, capture_output=True, text=True,
                              timeout=30)

    def test_models_start_prints_command_and_does_not_run(self):
        out = self._run("models", "start",
                        endpoint=f"http://127.0.0.1:{closed_port()}/x")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("systemctl --user start llama-jev.service "
                      "jev-shim.service", out.stdout)
        self.assertIn("--run", out.stdout)

    def test_models_status_lists_endpoints(self):
        jev = fakes.FakeJev({}).start()
        try:
            out = self._run("models", endpoint=jev.url + "/x")
        finally:
            jev.stop()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("jev", out.stdout)
        self.assertIn("ok", out.stdout)


if __name__ == "__main__":
    unittest.main()
