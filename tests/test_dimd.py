#!/usr/bin/env python3
"""Headless unit tests for the dim package's pure decision logic."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dim import config, pipeline  # noqa: E402


class TestLoadConfig(unittest.TestCase):
    def test_parses_toml_subset(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            cfg_file.write_text(
                '[audio]\nseconds = 7\n\n[agent]\nmodel = "m"\n'
                'risk_threshold = "1.5" # trailing comment\n')
            with mock.patch.object(config, "CFG_FILE", cfg_file):
                cfg = config.load_config()
        self.assertEqual(cfg["audio"]["seconds"], "7")
        self.assertEqual(cfg["agent"]["risk_threshold"], "1.5")

    def test_writes_default_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            with mock.patch.object(config, "CFG_FILE", cfg_file), \
                 mock.patch.object(config, "CFG_DIR", pathlib.Path(td)):
                cfg = config.load_config()
            self.assertTrue(cfg_file.exists())
            self.assertEqual(cfg["apps"]["terminal"], "ghostty")
            self.assertEqual(cfg["audio"]["whisper_model"],
                             "ggml-small.en.bin")


class TestExecute(unittest.TestCase):
    def setUp(self):
        self.cfg = {"agent": {"risk_threshold": "1.5"},
                    "apps": {"terminal": "ghostty"}}

    def answers(self, action="launch", app="terminal", risk=1.2):
        return {"action": {"choice": action},
                "app": {"choice": app},
                "risk": {"score": risk}}

    def test_blocks_high_risk(self):
        out = pipeline.execute(self.answers(action="type_text", risk=2.0),
                               self.cfg)
        self.assertTrue(out.startswith("BLOCKED"))

    def test_launch_route_not_risk_gated(self):
        # "open discord" scored risk 1.6 live — launches are never blocked
        from dim import tools
        with mock.patch.object(tools, "run", return_value="LAUNCHED"):
            out = pipeline.execute(
                self.answers(action="launch", app="browser", risk=2.5),
                self.cfg)
        self.assertEqual(out, "LAUNCHED")

    def test_skips_non_launch(self):
        out = pipeline.execute(self.answers(action="bogus"), self.cfg)
        self.assertTrue(out.startswith("SKIP"))

    def test_close_dispatches_tool(self):
        from dim import tools
        with mock.patch.object(tools, "run", return_value="CLOSED") as r:
            out = pipeline.execute(self.answers(action="close"), self.cfg)
        self.assertEqual(out, "CLOSED")
        r.assert_called_once()

    def test_answer_route_never_executes(self):
        out = pipeline.execute(self.answers(action="answer", app="none"),
                               self.cfg)
        self.assertEqual(out, "ANSWERED")

    def test_skips_unknown_app(self):
        out = pipeline.execute(self.answers(app="emacs"), self.cfg)
        self.assertIn("unknown app", out)

    def test_skips_missing_binary(self):
        with mock.patch.object(pipeline.shutil, "which", return_value=None), \
             mock.patch.object(pipeline.pathlib.Path, "exists",
                               return_value=False):
            out = pipeline.execute(self.answers(), self.cfg)
        self.assertIn("not installed", out)

    def test_launch_uses_lua_dispatcher(self):
        ok = mock.Mock(returncode=0, stdout="ok")
        with mock.patch.object(pipeline.shutil, "which",
                               return_value="/usr/bin/ghostty"), \
             mock.patch.object(pipeline.subprocess, "run",
                               return_value=ok) as run:
            out = pipeline.execute(self.answers(), self.cfg)
        self.assertIn("LAUNCHED", out)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:2], ["hyprctl", "eval"])
        self.assertIn('hl.dsp.exec_cmd("ghostty")', cmd[2])

    def test_launch_falls_back_to_dispatch(self):
        fail = mock.Mock(returncode=1, stdout="err")
        with mock.patch.object(pipeline.shutil, "which",
                               return_value="/usr/bin/ghostty"), \
             mock.patch.object(pipeline.subprocess, "run",
                               return_value=fail) as run:
            out = pipeline.execute(self.answers(), self.cfg)
        self.assertIn("LAUNCHED", out)
        self.assertEqual(run.call_args_list[-1][0][0],
                         ["hyprctl", "dispatch", "exec", "ghostty"])


class TestConfidenceGate(unittest.TestCase):
    """Gate is on app/target confidence only — low action confidence must
    not kill a correct launch (the 'retro-large' regression)."""

    def cfg(self, thresh="0.8"):
        return {"agent": {"confidence_ambiguous": thresh}}

    def answers(self, app_conf, act_conf):
        return {"app": {"choice": "retroarch", "confidence": app_conf,
                        "probabilities": {"retroarch": app_conf}},
                "action": {"choice": "launch", "confidence": act_conf,
                           "probabilities": {"launch": act_conf}}}

    def test_high_app_low_action_not_low_confidence(self):
        self.assertFalse(
            pipeline.is_low_confidence(self.answers(0.9, 0.49), self.cfg()))

    def test_low_app_is_low_confidence(self):
        self.assertTrue(
            pipeline.is_low_confidence(self.answers(0.4, 0.9), self.cfg()))


class TestChoiceFlow(unittest.TestCase):
    def answers(self):
        return {"app": {"choice": "terminal", "confidence": 0.5,
                        "probabilities": {"terminal": 0.5, "browser": 0.3}},
                "action": {"choice": "launch", "confidence": 0.5,
                           "probabilities": {"launch": 0.5}}}

    def test_choices_list_top_candidates(self):
        labels = pipeline.ambiguous_choices(self.answers(), {})
        self.assertIn("app:terminal", labels)
        self.assertIn("app:browser", labels)
        self.assertIn("action:launch", labels)

    def test_apply_choice_corrects_answers(self):
        out = pipeline.apply_choice(self.answers(), "app:browser")
        self.assertEqual(out["app"]["choice"], "browser")
        self.assertTrue(out["corrected_by_user"])

class TestLogDecision(unittest.TestCase):
    def test_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            target = pathlib.Path(td) / "decisions.jsonl"
            pipeline.log_decision({"ts": "t1", "result": "LAUNCHED"},
                                  log_file=target)
            pipeline.log_decision({"ts": "t2", "result": "BLOCKED"},
                                  log_file=target)
            rows = [json.loads(l) for l in target.read_text().splitlines()]
        self.assertEqual([r["result"] for r in rows], ["LAUNCHED", "BLOCKED"])


if __name__ == "__main__":
    unittest.main()
