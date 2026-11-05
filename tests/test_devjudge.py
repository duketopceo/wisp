#!/usr/bin/env python3
"""Dev tuning mode U3: the task judge. The brain call is stubbed, so
nothing here touches the network, a key or the desktop."""
import json
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from wisp import blank, brain, config, devjudge, ledger, learn  # noqa: E402
from wisp import stage_capture  # noqa: E402

SHOT = "data:image/png;base64,VETTED"
EVAL_KEY = "omaseal://openrouter/orchestral,OPENROUTER_API_KEY"


class Base(unittest.TestCase):
    def setUp(self):
        td = shorttmp.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        for obj, name, val in (
                (config, "DATA_DIR", self.dir),
                (config, "DECISIONS", self.dir / "decisions.jsonl"),
                (learn, "LABELS_FILE", self.dir / "labels.jsonl")):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.cfg = config._default_cfg_dict()
        self.cfg["brain"]["default"] = "openrouter:google/gemini-2.5-flash"
        self.cfg["brain"]["fallback"] = \
            "openrouter:meta-llama/llama-4-maverick"
        self.reqs = []
        self.replies = []
        self.cost = 0.002
        self.shot = SHOT
        for obj, name, fn in (
                (brain, "_chat_one", self.fake_chat),
                (stage_capture, "_vetted_b64", lambda: self.shot)):
            p = mock.patch.object(obj, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def fake_chat(self, p, messages, tools, timeout):
        self.reqs.append((dict(p), messages))
        reply = self.replies.pop(0) if self.replies else json.dumps(
            {"outcome": "success", "reason": "the page is open"})
        if isinstance(reply, Exception):
            raise reply
        return {"content": reply,
                "usage": {"in": 900, "out": 30, "cost": self.cost}}

    def judge(self, goal="open my stripe tab", steps=None):
        j = devjudge.Judge(self.cfg)
        return j, j.judge(goal, steps if steps is not None else
                          [{"tool": "launch", "arg": "stripe",
                            "result": "LAUNCHED"}])


class TestRequest(Base):
    def test_request_uses_the_eval_provider_never_the_default_key(self):
        before = json.dumps(self.cfg, sort_keys=True)
        _, out = self.judge()
        self.assertEqual(out["outcome"], "success")
        self.assertEqual(len(self.reqs), 1)
        p, msgs = self.reqs[0]
        self.assertEqual(p["name"], "orcheval")
        self.assertEqual(p["key_env"], EVAL_KEY)
        self.assertEqual(p["model"], "google/gemini-2.5-flash")
        self.assertIn("openrouter.ai", p["base_url"])
        self.assertTrue(p["paid"])
        self.assertNotEqual(p["key_env"], "OPENROUTER_API_KEY")
        # the owner's config is unchanged and carries no eval provider
        self.assertEqual(json.dumps(self.cfg, sort_keys=True), before)
        self.assertNotIn("brain.orcheval", self.cfg)

    def test_run_config_has_no_fallback_to_the_default_key(self):
        jc = devjudge.judge_cfg(self.cfg, "x/y")
        self.assertEqual([p["name"] for p in brain.chain(jc)], ["orcheval"])
        self.assertEqual(brain.chain(jc)[0]["model"], "x/y")
        self.assertEqual(self.cfg["brain"]["fallback"],
                         "openrouter:meta-llama/llama-4-maverick")

    def test_judge_model_is_a_setting(self):
        self.cfg.setdefault("dev", {})["judge_model"] = "acme/vision-1"
        self.judge()
        self.assertEqual(self.reqs[0][0]["model"], "acme/vision-1")

    def test_default_model_is_a_cheap_gemini_flash(self):
        self.assertEqual(devjudge.settings(self.cfg)["model"],
                         "google/gemini-2.5-flash")
        self.assertEqual(devjudge.settings(self.cfg)["cap_usd"], 1.0)

    def test_message_carries_goal_steps_and_the_vetted_shot(self):
        self.judge("pause youtube",
                   [{"tool": "media", "arg": "pause", "result": "paused"}])
        msgs = self.reqs[0][1]
        parts = msgs[1]["content"]
        urls = [x["image_url"]["url"] for x in parts
                if x["type"] == "image_url"]
        self.assertEqual(urls, [SHOT])
        text = "".join(x["text"] for x in parts if x["type"] == "text")
        self.assertIn(json.dumps("pause youtube"), text)   # quoted JSON
        self.assertIn("media", text)
        self.assertIn("stopped", msgs[0]["content"])
        self.assertIn("wrong_tries", msgs[0]["content"])


class TestVettedCapture(Base):
    def test_the_vetted_capture_is_the_only_screenshot_source(self):
        with mock.patch.object(stage_capture, "_vetted_b64",
                               return_value=SHOT) as v:
            self.judge()
        v.assert_called_once()

    def test_no_shot_means_no_model_call_and_unjudged(self):
        for shot in (None, blank.Blind("black frame")):
            with self.subTest(shot=repr(shot)):
                self.shot = shot
                self.reqs.clear()
                _, out = self.judge()
                self.assertEqual(out["outcome"], "unjudged")
                self.assertIn("screenshot", out["reason"])
                self.assertEqual(self.reqs, [])


    def test_screenshots_off_means_no_capture_and_unjudged(self):
        self.cfg["agent"]["screenshots"] = "false"
        with mock.patch.object(stage_capture, "_vetted_b64") as v:
            _, out = self.judge()
        v.assert_not_called()
        self.assertEqual(out["outcome"], "unjudged")
        self.assertEqual(self.reqs, [])


class TestParse(Base):
    def test_malformed_reply_is_unjudged(self):
        for bad in ("looks fine to me", "", "{not json}",
                    json.dumps({"outcome": "great", "reason": "x"}),
                    json.dumps({"reason": "no outcome"}),
                    json.dumps(["success"])):
            with self.subTest(bad=bad):
                self.replies = [bad]
                _, out = self.judge()
                self.assertEqual(out["outcome"], "unjudged")

    def test_the_four_outcomes_parse(self):
        for o in ("success", "stopped", "incomplete", "wrong_tries"):
            with self.subTest(o=o):
                self.replies = [json.dumps({"outcome": o, "reason": "r"})]
                _, out = self.judge()
                self.assertEqual(out["outcome"], o)
                self.assertEqual(out["reason"], "r")

    def test_provider_error_is_unjudged_not_raised(self):
        self.replies = [RuntimeError("boom")]
        _, out = self.judge()
        self.assertEqual(out["outcome"], "unjudged")

    def test_reply_text_never_becomes_an_instruction(self):
        self.replies = ['{"outcome": "success", "reason": "' + "x" * 900
                        + '"}']
        _, out = self.judge()
        self.assertLessEqual(len(out["reason"]), 200)


class TestSpend(Base):
    def test_cost_goes_through_the_ledger_tagged_as_eval_spend(self):
        with mock.patch.object(ledger, "note") as note:
            j, out = self.judge()
        self.assertEqual(note.call_args[0][0], "orcheval")
        self.assertAlmostEqual(out["cost_usd"], 0.002)
        self.assertAlmostEqual(j.spent, 0.002)

    def test_cap_stops_judging_and_marks_the_rest_unjudged(self):
        self.cfg.setdefault("dev", {})["judge_cap_usd"] = "0.01"
        self.cost = 0.006
        j = devjudge.Judge(self.cfg)
        outs = [j.judge(f"task {i}", []) for i in range(4)]
        self.assertEqual([o["outcome"] for o in outs],
                         ["success", "success", "unjudged", "unjudged"])
        self.assertEqual(outs[2]["reason"], "cap")
        self.assertEqual(len(self.reqs), 2)
        self.assertTrue(j.capped)
        self.assertEqual(outs[3]["cost_usd"], 0.0)

    def test_zero_cap_judges_nothing(self):
        self.cfg.setdefault("dev", {})["judge_cap_usd"] = "0"
        _, out = self.judge()
        self.assertEqual(out["outcome"], "unjudged")
        self.assertEqual(self.reqs, [])

    def test_cap_reads_the_setting_default_one_dollar(self):
        self.assertEqual(devjudge.settings({})["cap_usd"], 1.0)
        self.assertEqual(devjudge.settings(
            {"dev": {"judge_cap_usd": "junk"}})["cap_usd"], 1.0)
        self.assertEqual(devjudge.settings(
            {"dev": {"judge_cap_usd": "2.5"}})["cap_usd"], 2.5)


class TestLabelsUntouched(Base):
    def test_judging_never_writes_labels(self):
        j = devjudge.Judge(self.cfg)
        j.judge("a", [])
        j.judge("b", [])
        self.assertFalse(learn.LABELS_FILE.exists())


if __name__ == "__main__":
    unittest.main()
