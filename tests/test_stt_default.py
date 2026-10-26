#!/usr/bin/env python3
"""Hosted STT is the shipped default; `provider = "local"` is opt-in."""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from wisp import config, onboard, pipeline  # noqa: E402
from wisp import settings_schema  # noqa: E402


class _Resp:
    def read(self):
        return b'{"text": "hello"}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _transcribe(cfg):
    """Run pipeline.transcribe against a fake endpoint; return the
    captured request and the text."""
    wav = pathlib.Path(tempfile.mktemp(suffix=".wav"))
    wav.write_bytes(b"RIFFfake")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return _Resp()

    try:
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gk-test"}), \
             mock.patch.object(pipeline.urllib.request, "urlopen",
                               fake_urlopen):
            return pipeline.transcribe(wav, cfg), captured
    finally:
        wav.unlink(missing_ok=True)


class TestHostedDefault(unittest.TestCase):
    def test_no_stt_section_uses_hosted_groq(self):
        text, cap = _transcribe({})
        self.assertEqual(text, "hello")
        self.assertEqual(
            cap["url"], "https://api.groq.com/openai/v1/audio/transcriptions")
        self.assertIn(b"whisper-large-v3-turbo", cap["body"])

    def test_prompt_only_section_keeps_hosted_provider_and_prompt(self):
        cfg = {"stt": {"prompt": "Zorblax", "vocab_dynamic": "false"}}
        self.assertEqual(config.stt_settings(cfg)["provider"], "openai")
        _, cap = _transcribe(cfg)
        self.assertIn(b"Zorblax", cap["body"])
        self.assertIn("groq.com", cap["url"])

    def test_explicit_values_win_over_defaults(self):
        s = config.stt_settings({"stt": {
            "base_url": "https://example.test/v1", "key_env": "X_KEY"}})
        self.assertEqual(s["base_url"], "https://example.test/v1")
        self.assertEqual(s["key_env"], "X_KEY")
        self.assertEqual(s["model"], "whisper-large-v3-turbo")

    def test_explicit_local_selects_whisper_cpp(self):
        cfg = {"stt": {"provider": "local"}}
        with mock.patch.object(pipeline.urllib.request, "urlopen",
                               side_effect=AssertionError("hosted path")), \
             mock.patch.object(config, "WHISPER_BIN",
                               pathlib.Path("/nonexistent/whisper-cli")):
            with self.assertRaises(RuntimeError) as cm:
                pipeline.transcribe(pathlib.Path("/tmp/x.wav"), cfg)
        self.assertIn("whisper.cpp missing", str(cm.exception))

    def test_mic_check_model_only_needed_for_local(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(config, "WHISPER_HOME", pathlib.Path(td)):
            self.assertTrue(onboard._whisper_ok({}))
            self.assertTrue(onboard._whisper_ok({"stt": {"prompt": "x"}}))
            self.assertFalse(
                onboard._whisper_ok({"stt": {"provider": "local"}}))


class TestShippedDefaults(unittest.TestCase):
    def test_default_config_text_and_schema_say_openai(self):
        self.assertIn('provider = "openai"', config.DEFAULT_CONFIG)
        self.assertNotIn('provider = "local"', config.DEFAULT_CONFIG)
        field = next(f for f in settings_schema.FIELDS
                     if f.key == "stt.provider") \
            if hasattr(settings_schema, "FIELDS") else None
        if field is not None:
            self.assertEqual(field.default, "openai")


if __name__ == "__main__":
    unittest.main()
