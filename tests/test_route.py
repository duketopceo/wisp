"""Jev accelerator, heuristic router and route A/B log (W11, backend U8).

Jev answers under a deadline; past it, or on any failure, a heuristic
route decides and the turn continues. Fakes only: Jev is a loopback
HTTP server, nothing here leaves the machine.
"""
import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import fakes  # noqa: E402
from cli_env import CliEnv  # noqa: E402
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
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ab = pathlib.Path(self.tmp.name) / "route_ab.jsonl"
        for name, val in (("ROUTE_AB", self.ab),):
            p = mock.patch.object(config, name, val, create=True)
            p.start()
            self.addCleanup(p.stop)

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


class AbLogTest(RouteBase):
    def test_disagreement_logged_with_fields(self):
        self.jev(ANSWER)
        _, meta = self.decide("open firefox")
        route.log_ab(meta, "open firefox", "t-1", "launch")
        rec = json.loads(self.ab.read_text().splitlines()[0])
        for k in ("ts", "turn", "transcript", "jev", "heuristic", "final",
                  "agree", "deadline_ms"):
            self.assertIn(k, rec)
        self.assertEqual(rec["jev"]["route"], "answer")
        self.assertEqual(rec["jev"]["status"], "ok")
        self.assertIsInstance(rec["jev"]["ms"], int)
        self.assertEqual(rec["heuristic"]["route"], "launch")
        self.assertEqual(rec["heuristic"]["rule"], "bare_launch")
        self.assertEqual(rec["final"], {"route": "launch",
                                        "source": "heuristic"})
        self.assertFalse(rec["agree"])
        self.assertEqual(rec["turn"], "t-1")

    def test_jev_down_is_logged_with_null_agreement(self):
        self.jev({"status": 502})
        _, meta = self.decide("what time is it")
        route.log_ab(meta, "what time is it", "t-2", "answer")
        rec = json.loads(self.ab.read_text())
        self.assertEqual(rec["jev"]["status"], "error")
        self.assertIsNone(rec["jev"]["route"])
        self.assertIsNone(rec["agree"])

    def test_log_failure_never_raises(self):
        with mock.patch.object(config, "ROUTE_AB",
                               pathlib.Path("/proc/nope/x.jsonl")):
            route.log_ab({"source": "heuristic"}, "x", "t", "answer")


def _seed(env, rows):
    env.data.mkdir(parents=True, exist_ok=True)
    (env.data / "route_ab.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))


def _row(jev, heur, final, status="ok", ms=90, source="jev", t="x"):
    return {"ts": "2026-10-04T10:00:00+00:00", "turn": t, "transcript": t,
            "deadline_ms": 400,
            "jev": {"route": jev, "status": status, "ms": ms},
            "heuristic": {"route": heur, "rule": "r", "ms": 1},
            "final": {"route": final, "source": source},
            "agree": None if jev is None else jev == heur,
            "override": source == "heuristic" and status == "ok"}


class EvalRouteCliTest(unittest.TestCase):
    ROWS = [
        _row("answer", "answer", "answer", t="a"),
        _row("launch", "launch", "launch", ms=120, t="b"),
        _row("answer", "launch", "launch", source="heuristic", t="c"),
        _row(None, "answer", "answer", status="timeout", ms=400,
             source="heuristic", t="d"),
    ]

    def test_text_report(self):
        with CliEnv() as env:
            _seed(env, self.ROWS)
            code, out, err = env.run(["eval", "route"])
        self.assertEqual(code, 0, err)
        self.assertIn("4 turns", out)
        self.assertIn("agree", out)
        self.assertIn("timeout", out)
        self.assertIn("answer -> launch", out)      # the disagreement

    def test_json_report(self):
        with CliEnv() as env:
            _seed(env, self.ROWS)
            code, out, err = env.run(["eval", "route", "--json"])
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        d = d.get("data", d)
        self.assertEqual(d["turns"], 4)
        self.assertEqual(d["jev_answered"], 3)
        self.assertEqual(d["agreed"], 2)
        self.assertAlmostEqual(d["agreement"], 2 / 3, places=3)
        self.assertEqual(d["overrides"], 1)
        self.assertEqual(d["jev_status"], {"ok": 3, "timeout": 1})
        self.assertEqual(d["final_source"], {"jev": 2, "heuristic": 2})
        self.assertIn("p50", d["jev_ms"])
        self.assertEqual(len(d["disagreements"]), 1)
        self.assertEqual(d["disagreements"][0]["jev"], "answer")
        self.assertEqual(d["disagreements"][0]["heuristic"], "launch")

    def test_limit_takes_latest(self):
        with CliEnv() as env:
            _seed(env, self.ROWS)
            code, out, _ = env.run(["eval", "route", "2", "--json"])
        d = json.loads(out)
        d = d.get("data", d)
        self.assertEqual(d["turns"], 2)

    def test_empty_log(self):
        with CliEnv() as env:
            code, out, _ = env.run(["eval", "route"])
        self.assertEqual(code, 0)
        self.assertIn("no routed turns", out)


if __name__ == "__main__":
    unittest.main()
