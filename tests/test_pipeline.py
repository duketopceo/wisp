#!/usr/bin/env python3
"""Pipeline unit tests."""
import pathlib
import shutil
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import pipeline  # noqa: E402

class SttPromptTest(unittest.TestCase):
    def test_local_whisper_gets_prompt(self):
        from unittest import mock
        import pathlib, tempfile
        wav = pathlib.Path(tempfile.mkdtemp()) / "a.wav"
        wav.write_bytes(b"x")
        cfg = {"stt": {"prompt": "Omarchy, Wisp"}}
        calls = {}
        def fake_run(argv, **kw):
            calls["argv"] = argv
            class R: stdout = "hello omarchy"
            return R()
        import tempfile as _tf
        from wisp import vocab as _v
        # /bin/true is Linux-only; resolve a real binary so the
        # existence check in transcribe() passes on any host.
        _true = pathlib.Path(shutil.which("true") or "/usr/bin/true")
        with mock.patch.object(_v, "CACHE",
                               pathlib.Path(_tf.mkdtemp()) / "v.txt"), \
             mock.patch.object(pipeline.config, "WHISPER_BIN", _true), \
             mock.patch.object(pipeline.config, "whisper_model",
                               lambda c: _true), \
             mock.patch.object(pipeline.subprocess, "run", fake_run):
            out = pipeline.transcribe(wav, cfg)
        self.assertIn("--prompt", calls["argv"])
        pi = calls["argv"].index("--prompt")
        self.assertIn("Omarchy", calls["argv"][pi + 1])
        self.assertEqual(out, "hello omarchy")


class VocabTest(unittest.TestCase):
    def test_collect_merges_sources(self):
        import tempfile
        from unittest import mock
        from wisp import vocab
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "harness.json").write_text(
            '{"apps": {"retroarch": {}, "discord": {}}}')
        with mock.patch.object(vocab, "HARNESS",
                               d / "harness.json"), \
             mock.patch.object(vocab, "ACTIVITY", d / "none"):
            terms = vocab.collect({"stt": {"prompt": "Omarchy, Jev"}})
        low = [t.lower() for t in terms]
        self.assertIn("retroarch", low)
        self.assertIn("omarchy", low)
        self.assertIn("jev", low)

    def test_static_when_disabled(self):
        from wisp import vocab
        out = vocab.build({"stt": {"prompt": "static",
                                   "vocab_dynamic": "false"}})
        self.assertEqual(out, "static")
