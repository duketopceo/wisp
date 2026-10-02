#!/usr/bin/env python3
"""Headless unit tests for the wisp package's pure decision logic."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import config, pipeline  # noqa: E402


def _with_os(os_name):
    """Pin the platform seam so adapter assertions are host-independent."""
    return mock.patch.dict(os.environ, {"WISP_OS": os_name})


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
            # [apps] defaults are host-specific — pin the seam so the
            # assertion means the same thing on every dev machine.
            with _with_os("linux"), \
                 mock.patch.object(config, "CFG_FILE", cfg_file), \
                 mock.patch.object(config, "CFG_DIR", pathlib.Path(td)):
                cfg = config.load_config()
            self.assertTrue(cfg_file.exists())
            self.assertEqual(cfg["apps"]["terminal"], "ghostty")
            self.assertEqual(cfg["audio"]["whisper_model"],
                             "ggml-small.en.bin")

    def test_default_config_written_for_host(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            with _with_os("macos"), \
                 mock.patch.object(config, "CFG_FILE", cfg_file), \
                 mock.patch.object(config, "CFG_DIR", pathlib.Path(td)):
                cfg = config.load_config()
            self.assertEqual(cfg["apps"]["terminal"], "open -a 'Terminal'")
            self.assertIn('[apps]', cfg_file.read_text())


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
        from wisp import tools
        with mock.patch.object(tools, "run", return_value="LAUNCHED"):
            out = pipeline.execute(
                self.answers(action="launch", app="browser", risk=2.5),
                self.cfg)
        self.assertEqual(out, "LAUNCHED")

    def test_skips_non_launch(self):
        out = pipeline.execute(self.answers(action="bogus"), self.cfg)
        self.assertTrue(out.startswith("SKIP"))

    def test_close_dispatches_tool(self):
        from wisp import tools
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

    def test_dictation_route_types_transcript(self):
        from wisp import tools
        ans = {"route": {"choice": "dictation"},
               "action": {"choice": ""}, "app": {"choice": "none"},
               "risk": {"score": 1.0}}
        with mock.patch.object(tools, "run", return_value="TYPED") as r:
            out = pipeline.execute(ans, self.cfg,
                                   detail="dictate hello there")
        self.assertEqual(out, "TYPED")
        r.assert_called_once_with("type_text", "hello there", self.cfg)

    def test_dictation_not_risk_gated(self):
        # dictation is self-confirming: transcript is the user's own
        # instruction — high Jev risk score must not block it
        from wisp import tools
        ans = {"route": {"choice": "dictation"},
               "action": {"choice": ""}, "app": {"choice": "none"},
               "risk": {"score": 2.0}}
        with mock.patch.object(tools, "run", return_value="TYPED") as r:
            out = pipeline.execute(ans, self.cfg, detail="dictate x")
        self.assertEqual(out, "TYPED")
        r.assert_called_once()

    def test_dictation_text_strips_prefix(self):
        cases = {
            "dictate hello": "hello",
            "Dictate: buy milk": "buy milk",
            "please type this, ok": "ok",
            "take dictation meeting notes": "meeting notes",
            "write this down - the thing": "the thing",
            "typesetter is an app": "typesetter is an app",
            "dictated": "dictated",
            "dictate": "dictate",  # prefix-only → keep original
            "hello world": "hello world",
        }
        for raw, want in cases.items():
            self.assertEqual(pipeline.dictation_text(raw), want, raw)

    def test_launch_uses_lua_dispatcher(self):
        ok = mock.Mock(returncode=0, stdout="ok")
        with _with_os("linux"), \
             mock.patch.object(pipeline.shutil, "which",
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
        with _with_os("linux"), \
             mock.patch.object(pipeline.shutil, "which",
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


class TestSttProvider(unittest.TestCase):
    def test_openai_provider_posts_multipart(self):
        wav = pathlib.Path(tempfile.mktemp(suffix=".wav"))
        wav.write_bytes(b"RIFFfake")
        self.addCleanup(wav.unlink, True)
        captured = {}

        class Resp:
            def read(self):
                return b'{"text": "hello  world "}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["auth"] = req.headers.get("Authorization")
            captured["ctype"] = req.headers.get("Content-type")
            captured["body"] = req.data
            return Resp()

        cfg = {"stt": {"provider": "openai",
                       "base_url": "https://api.groq.com/openai/v1/",
                       "model": "whisper-large-v3-turbo",
                       "key_env": "GROQ_API_KEY"}}
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gk-test"}), \
             mock.patch.object(pipeline.urllib.request, "urlopen",
                               fake_urlopen):
            out = pipeline.transcribe(wav, cfg)
        self.assertEqual(out, "hello world")
        self.assertEqual(captured["url"],
                         "https://api.groq.com/openai/v1/audio/transcriptions")
        self.assertEqual(captured["auth"], "Bearer gk-test")
        self.assertIn("multipart/form-data", captured["ctype"])
        self.assertIn(b'name="model"', captured["body"])
        self.assertIn(b"RIFFfake", captured["body"])

    def test_missing_key_raises(self):
        cfg = {"stt": {"provider": "openai", "key_env": "NO_SUCH_KEY_XYZ"}}
        with self.assertRaises(RuntimeError):
            pipeline.transcribe(pathlib.Path("/tmp/x.wav"), cfg)


if __name__ == "__main__":
    unittest.main()
