#!/usr/bin/env python3
"""Headless unit tests for dimd's pure decision logic.

Loads dimd (extensionless script) via importlib; monkeypatches filesystem
constants so no real config, overlay, or hyprctl is touched.
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

DIMD = pathlib.Path(__file__).resolve().parent.parent / "dimd"
_loader = importlib.machinery.SourceFileLoader("dimd", str(DIMD))
spec = importlib.util.spec_from_loader("dimd", _loader)
dimd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dimd)


class TestLoadConfig(unittest.TestCase):
    def test_parses_toml_subset(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            cfg_file.write_text(
                '[audio]\nseconds = 7\n\n[agent]\nmodel = "m"\n'
                'risk_threshold = "1.5" # trailing comment\n')
            with mock.patch.object(dimd, "CFG_FILE", cfg_file):
                cfg = dimd.load_config()
        self.assertEqual(cfg["audio"]["seconds"], "7")
        self.assertEqual(cfg["agent"]["risk_threshold"], "1.5")

    def test_writes_default_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            with mock.patch.object(dimd, "CFG_FILE", cfg_file), \
                 mock.patch.object(dimd, "CFG_DIR", pathlib.Path(td)):
                cfg = dimd.load_config()
            self.assertTrue(cfg_file.exists())
            self.assertEqual(cfg["apps"]["terminal"], "ghostty")


class TestExecute(unittest.TestCase):
    def setUp(self):
        self.cfg = {"agent": {"risk_threshold": "1.5"},
                    "apps": {"terminal": "ghostty"}}

    def answers(self, action="launch", app="terminal", risk=1.2):
        return {"action": {"choice": action},
                "app": {"choice": app},
                "risk": {"score": risk}}

    def test_blocks_high_risk(self):
        out = dimd.execute(self.answers(risk=2.0), self.cfg)
        self.assertTrue(out.startswith("BLOCKED"))

    def test_skips_non_launch(self):
        out = dimd.execute(self.answers(action="close"), self.cfg)
        self.assertTrue(out.startswith("SKIP"))

    def test_skips_unknown_app(self):
        out = dimd.execute(self.answers(app="emacs"), self.cfg)
        self.assertIn("unknown app", out)

    def test_launch_uses_lua_dispatcher(self):
        ok = mock.Mock(returncode=0, stdout="ok")
        with mock.patch.object(dimd.subprocess, "run", return_value=ok) as run:
            out = dimd.execute(self.answers(), self.cfg)
        self.assertIn("LAUNCHED", out)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:2], ["hyprctl", "eval"])
        self.assertIn('hl.dsp.exec_cmd("ghostty")', cmd[2])

    def test_launch_falls_back_to_dispatch(self):
        fail = mock.Mock(returncode=1, stdout="err")
        with mock.patch.object(dimd.subprocess, "run", return_value=fail) as run:
            out = dimd.execute(self.answers(), self.cfg)
        self.assertIn("LAUNCHED", out)
        self.assertEqual(run.call_args_list[-1][0][0],
                         ["hyprctl", "dispatch", "exec", "ghostty"])


class TestAmbiguousChoice(unittest.TestCase):
    def cfg(self, thresh="0.8"):
        return {"agent": {"confidence_ambiguous": thresh}}

    def answers(self, conf):
        return {"app": {"choice": "terminal", "confidence": conf,
                        "probabilities": {"terminal": conf, "browser": 1 - conf}},
                "action": {"choice": "launch", "confidence": conf,
                           "probabilities": {"launch": conf}}}

    def test_high_confidence_passes_through(self):
        self.assertIsNone(dimd.ambiguous_choice(self.answers(0.9), self.cfg()))

    def test_low_confidence_offers_buttons(self):
        picked = mock.Mock(returncode=0, stdout="app:browser\n")
        with mock.patch.object(dimd.subprocess, "run", return_value=picked) as run:
            out = dimd.ambiguous_choice(self.answers(0.5), self.cfg())
        self.assertEqual(out["app"]["choice"], "browser")
        self.assertTrue(out["corrected_by_user"])
        self.assertEqual(run.call_args[0][0][1], "--buttons")

    def test_cancel_returns_none(self):
        picked = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(dimd.subprocess, "run", return_value=picked):
            self.assertIsNone(
                dimd.ambiguous_choice(self.answers(0.5), self.cfg()))


class TestLogDecision(unittest.TestCase):
    def test_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            target = pathlib.Path(td) / "corrections.jsonl"
            with mock.patch.object(dimd, "CORRECTIONS", target):
                dimd.log_decision({"ts": "t1", "result": "LAUNCHED"})
                dimd.log_decision({"ts": "t2", "result": "BLOCKED"})
            rows = [json.loads(l) for l in target.read_text().splitlines()]
        self.assertEqual([r["result"] for r in rows], ["LAUNCHED", "BLOCKED"])


if __name__ == "__main__":
    unittest.main()
