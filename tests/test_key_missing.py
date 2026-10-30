#!/usr/bin/env python3
"""A turn that needs a key it cannot find ends with `key_missing`, and a
slow keyring lookup cannot hang it."""
import os
import pathlib
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from wisp import brain, config, errors_codes, pipeline, route  # noqa: E402
from wisp import state as wstate  # noqa: E402


class _NoKeys(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        env = mock.patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        envf = mock.patch.object(config, "ENV_FILE",
                                 pathlib.Path(td.name) / ".env")
        envf.start()
        self.addCleanup(envf.stop)


class TestKeyMissing(_NoKeys):
    def test_code_is_in_the_closed_set_with_copy(self):
        self.assertIn("key_missing", errors_codes.CODES)
        from wisp import copy as wcopy
        self.assertIn("wispd onboard", wcopy.ERRORS["key_missing"][1])

    def test_stt_without_a_key_names_groq_and_onboard(self):
        wav = pathlib.Path(tempfile.mktemp(suffix=".wav"))
        wav.write_bytes(b"RIFFfake")
        self.addCleanup(lambda: wav.unlink(missing_ok=True))
        with self.assertRaises(errors_codes.WispError) as cm:
            pipeline.transcribe(wav, {})
        self.assertEqual(cm.exception.code, "key_missing")
        self.assertIn("GROQ_API_KEY", cm.exception.public)
        self.assertIn("wispd onboard", cm.exception.public)

    def test_omaseal_ref_list_names_the_env_var_not_the_ref(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(errors_codes.WispError) as cm:
                config.require_key("omaseal://groq/default,GROQ_API_KEY")
        self.assertIn("GROQ_API_KEY", cm.exception.public)

    def test_turn_error_is_published_as_key_missing_without_traceback(self):
        st = wstate.State(
            state_file=pathlib.Path(tempfile.mkdtemp()) / "state.json")
        with self.assertRaises(errors_codes.WispError) as cm:
            config.load_api_key()
        pipeline._publish_error(st, cm.exception)
        snap = st.snapshot()
        self.assertEqual(snap["error_code"], "key_missing")
        self.assertIn("OPENROUTER_API_KEY", snap["error"])
        self.assertNotIn("Traceback", snap["error"])

    def test_openrouter_missing_is_key_missing(self):
        with self.assertRaises(errors_codes.WispError) as cm:
            config.load_api_key()
        self.assertEqual(cm.exception.code, "key_missing")
        self.assertIn("OPENROUTER_API_KEY", cm.exception.public)
        self.assertIn("wispd onboard", cm.exception.public)

    def test_legacy_router_does_not_need_a_decision_provider_key(self):
        from wisp import stage_route
        with mock.patch.object(config, "JEV_ENDPOINT",
                               "https://openrouter.ai/api/alpha/decisions"):
            self.assertEqual(stage_route.fixed_route("hi", "jev"),
                             ("act", None))

    def test_brain_with_declared_key_env_and_no_key_is_key_missing(self):
        cfg = {"brain": {"default": "openrouter:m", "fallback": ""}}
        with mock.patch.object(brain, "HEALTH", None):
            with self.assertRaises(errors_codes.WispError) as cm:
                brain.chat([{"role": "user", "content": "hi"}], cfg)
        self.assertEqual(cm.exception.code, "key_missing")
        self.assertIn("OPENROUTER_API_KEY", cm.exception.public)

    def test_missing_primary_key_wins_over_a_capped_fallback(self):
        cfg = {"brain": {"default": "openrouter:m",
                         "fallback": "openrouter:m2", "allow_paid": "true"}}
        with mock.patch.object(brain, "HEALTH", None), \
                mock.patch.object(brain, "budget_ok",
                                  side_effect=lambda cfg, primary: primary):
            with self.assertRaises(errors_codes.WispError) as cm:
                brain.chat([{"role": "user", "content": "hi"}], cfg)
        self.assertEqual(cm.exception.code, "key_missing")

    def test_keyless_local_brain_is_not_asked_for_a_key(self):
        p = brain.provider({"brain": {"default": "ollama:m"}})
        self.assertEqual(brain._headers(p).get("Authorization"), None)


class TestOmasealTimeout(_NoKeys):
    def test_hung_omaseal_falls_through_to_env_within_the_bound(self):
        td = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(td, True))
        fake = td / "omaseal"
        fake.write_text("#!/bin/sh\nsleep 30\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        env = {"PATH": f"{td}:/usr/bin:/bin", "GROQ_API_KEY": "from-env"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(config, "OMASEAL_TIMEOUT_S", 0.3):
            t0 = time.monotonic()
            got = config.load_env_key("omaseal://groq/default,GROQ_API_KEY")
            dt = time.monotonic() - t0
        self.assertEqual(got, "from-env")
        self.assertLess(dt, 5)

    def test_default_bound_is_seconds_not_ten(self):
        self.assertLessEqual(config.OMASEAL_TIMEOUT_S, 5)


if __name__ == "__main__":
    unittest.main()
