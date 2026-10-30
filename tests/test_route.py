"""Jev accelerator and heuristic router (W11, backend U8).

Jev answers under a deadline; past it, or on any failure, a heuristic
route decides and the turn continues. Fakes only: Jev is a loopback
HTTP server, nothing here leaves the machine.
"""
import pathlib
import sys
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import fakes  # noqa: E402
from wisp import config, pipeline, route  # noqa: E402

APPS = {"firefox": {"launch": "firefox"}, "discord": {"launch": "discord"},
        "terminal": {"launch": "ghostty"}}

ANSWER = {"answers": {"route": {"choice": "answer"},
                      "app": {"choice": "none", "confidence": 0.9},
                      "risk": {"score": 0}}}
ACT = {"answers": {"route": {"choice": "act"},
                   "app": {"choice": "none", "confidence": 0.9},
                   "risk": {"score": 2}}}


class RouteBase(unittest.TestCase):
    def jev(self, script):
        srv = fakes.FakeJev(script)
        srv.start()
        self.addCleanup(srv.stop)
        p = mock.patch.object(config, "JEV_ENDPOINT", srv.url + "/decisions")
        p.start()
        self.addCleanup(p.stop)
        return srv

    def decide(self, text="what time is it", cfg=None):
        return route.decide(text, "m", {}, "", cfg or {}, APPS)


class DeadlineTest(RouteBase):
    def test_fast_jev_is_used(self):
        self.jev(dict(ANSWER, latency_ms=80))
        resp, meta = self.decide()
        self.assertEqual(meta["source"], "jev")
        self.assertEqual(resp["answers"]["route"]["choice"], "answer")
        self.assertEqual(meta["jev_status"], "ok")
        self.assertGreaterEqual(meta["jev_ms"], 60)
        self.assertLess(meta["jev_ms"], 400)

    def test_deadline_expiry_returns_heuristic_within_budget(self):
        self.jev(dict(ANSWER, latency_ms=2000))
        t0 = time.monotonic()
        resp, meta = self.decide("open firefox")
        took = (time.monotonic() - t0) * 1000
        self.assertLess(took, 700)          # 400 ms deadline + slack
        self.assertGreaterEqual(took, 380)
        self.assertEqual(meta["source"], "heuristic")
        self.assertEqual(meta["jev_status"], "timeout")
        self.assertEqual(resp["answers"]["route"]["choice"], "launch")
        self.assertEqual(resp["answers"]["app"]["choice"], "firefox")

    def test_deadline_is_configurable(self):
        self.jev(dict(ANSWER, latency_ms=300))
        _, meta = self.decide(cfg={"jev": {"deadline_ms": "100"}})
        self.assertEqual(meta["jev_status"], "timeout")
        self.assertEqual(meta["deadline_ms"], 100)

    def test_late_reply_is_discarded(self):
        self.jev(dict(ANSWER, latency_ms=700))
        resp, meta = self.decide("open firefox")
        time.sleep(0.5)                      # the late reply lands here
        self.assertEqual(resp["answers"]["route"]["choice"], "launch")
        self.assertEqual(meta["source"], "heuristic")

    def test_jev_502_falls_back_without_error(self):
        srv = self.jev({"status": 502})
        resp, meta = self.decide("open discord")
        self.assertEqual(meta["source"], "heuristic")
        self.assertEqual(meta["jev_status"], "error")
        self.assertEqual(meta["jev_code"], "jev_down")
        self.assertEqual(resp["answers"]["app"]["choice"], "discord")
        self.assertEqual(len(srv.calls), 1)     # no retry on an HTTP error

    def test_jev_unreachable_falls_back(self):
        with mock.patch.object(config, "JEV_ENDPOINT",
                               "http://127.0.0.1:9/x"):
            resp, meta = self.decide("open firefox")
        self.assertEqual(meta["source"], "heuristic")
        self.assertEqual(meta["jev_status"], "error")

    def test_jev_malformed_falls_back(self):
        for bad in ({"answers": "nope"},
                    {"answers": {"route": {"choice": "teleport"}}},
                    {"answers": {}}):
            with self.subTest(bad=bad):
                self.jev(bad)
                resp, meta = self.decide("what time is it")
                self.assertEqual(meta["source"], "heuristic")
                self.assertEqual(meta["jev_status"], "malformed")
                self.assertEqual(resp["answers"]["route"]["choice"],
                                 "answer")


class GateTest(RouteBase):
    def test_bare_launch_overrides_jev_and_logs_disagreement(self):
        self.jev(ANSWER)
        resp, meta = self.decide("open firefox")
        self.assertEqual(resp["answers"]["route"]["choice"], "launch")
        self.assertEqual(meta["source"], "heuristic")
        self.assertTrue(meta["override"])
        self.assertEqual(meta["jev_route"], "answer")
        self.assertFalse(meta["agree"])

    def test_compound_request_keeps_jev_act(self):
        self.jev(ACT)
        resp, meta = self.decide("open firefox and go to github")
        self.assertEqual(resp["answers"]["route"]["choice"], "act")
        self.assertEqual(meta["source"], "jev")
        self.assertFalse(meta["override"])

    def test_jev_route_kept_when_heuristic_is_not_a_bare_launch(self):
        self.jev(ACT)
        resp, meta = self.decide("what time is it")
        self.assertEqual(meta["source"], "jev")
        self.assertEqual(resp["answers"]["route"]["choice"], "act")
        self.assertFalse(meta["agree"])     # logged, but Jev still wins


class HeuristicTable(unittest.TestCase):
    CASES = [
        ("open firefox", "launch", "firefox"),
        ("Open the terminal.", "launch", "terminal"),
        ("launch Discord", "launch", "discord"),
        ("please start firefox", "launch", "firefox"),
        ("can you open discord", "launch", "discord"),
        ("wisp, pull up the terminal app", "launch", "terminal"),
        ("open firefox and go to github", "act", None),
        ("open discord on the settings page", "act", None),
        ("open the spreadsheet app", "act", None),
        ("click the blue button", "act", None),
        ("search for flights to denver", "act", None),
        ("dictate hello world", "dictation", None),
        ("take dictation", "dictation", None),
        ("type this meeting starts at noon", "dictation", None),
        ("write this down buy milk", "dictation", None),
        ("what time is it", "answer", None),
        ("how do I open a file in vim", "answer", None),
        ("why is the sky blue", "answer", None),
        ("tell me a joke", "answer", None),
        ("is it going to rain?", "answer", None),
        ("hello there", "answer", None),
        ("take a screenshot", "tool", None),
        ("go to workspace 3", "tool", None),
        ("have an agent research rust async", "agent", None),
        ("spawn an agent to fix the login bug", "agent", None),
        ("have opencode debug the failing test", "agent", None),
        ("debug this in the background", "agent", None),
        ("check my email", "act", None),
        ("go to my Stripe", "act", None),
        ("go to my Linear", "act", None),
        ("open up this setting", "act", None),
        ("debug this", "act", None),
        ("tell me what this does", "answer", None),
        ("tell me what's wrong here", "answer", None),
        ("show me what's wrong here", "answer", None),
        ("learn how to export a pdf", "learn", None),
        ("remember this workflow", "learn", None),
    ]

    def test_coverage_table(self):
        for text, want, app in self.CASES:
            with self.subTest(text):
                h = route.heuristic(text, APPS)
                self.assertEqual(h["route"], want, h)
                if app:
                    self.assertEqual(h["app"], app)
                    self.assertTrue(h["bare_launch"])
                else:
                    self.assertFalse(h["bare_launch"])
                self.assertTrue(h["rule"])

    def test_tool_rules_name_the_tool(self):
        self.assertEqual(route.heuristic("take a screenshot", APPS)["tool"],
                         "screenshot")
        self.assertEqual(route.heuristic("go to workspace 3", APPS)["tool"],
                         "workspace")

    def test_empty_and_noise_are_safe(self):
        for t in ("", "   ", "[BLANK_AUDIO]"):
            self.assertIn(route.heuristic(t, APPS)["route"],
                          ("answer", "clarify"))

    def test_fast(self):
        t0 = time.perf_counter()
        for _ in range(200):
            route.heuristic("open firefox and go to github", APPS)
        self.assertLess((time.perf_counter() - t0) / 200, 0.002)

    def test_answers_shape_feeds_execute(self):
        a = route.heuristic_answers(route.heuristic("open firefox", APPS))
        self.assertEqual(a["route"]["choice"], "launch")
        self.assertEqual(a["app"]["choice"], "firefox")
        self.assertGreaterEqual(a["app"]["confidence"], 0.8)
        self.assertEqual(a["risk"]["score"], 0)


class FastRouteTest(unittest.TestCase):
    """The no-model fast path in front of act (Phase 5)."""
    APPS = {"firefox": {}, "terminal": {}}

    def _fast(self, text, cfg=None):
        from wisp import stage_route
        return stage_route.fast_route(text, self.APPS, cfg or {})

    def test_bare_launch_of_a_catalog_app(self):
        ans, rule = self._fast("open firefox")
        self.assertEqual(rule, "bare_launch")
        self.assertEqual(ans["route"]["choice"], "launch")
        self.assertEqual(ans["app"]["choice"], "firefox")
        self.assertGreaterEqual(ans["app"]["confidence"], 0.8)

    def test_polite_launch_still_fast(self):
        ans, _ = self._fast("could you please open the terminal")
        self.assertEqual(ans["app"]["choice"], "terminal")

    def test_plain_questions_answer(self):
        for q in ("what does this error mean", "how do I undo this",
                  "where is the save button", "is this safe?"):
            got = self._fast(q)
            self.assertIsNotNone(got, q)
            self.assertEqual(got[0]["route"]["choice"], "answer", q)

    def test_ambiguous_turns_stay_in_act(self):
        for t in ("open firefox and go to github",   # compound
                  "open discord",                    # not in the catalog
                  "go to stripe.com",
                  "click the save button",
                  "how do I open a file and then save it",
                  "what is on my screen and click ok",
                  "check which window is focused"):  # no rule matches
            self.assertIsNone(self._fast(t), t)

    def test_switch_turns_the_path_off(self):
        cfg = {"brain": {"fast_path": "false"}}
        self.assertIsNone(self._fast("open firefox", cfg))
        self.assertIsNone(self._fast("what is this", cfg))


if __name__ == "__main__":
    unittest.main()
