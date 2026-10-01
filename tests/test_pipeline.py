#!/usr/bin/env python3
"""Pipeline unit tests."""
import pathlib
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
        with mock.patch.object(pipeline.config, "WHISPER_BIN",
                               pathlib.Path("/bin/true")), \
             mock.patch.object(pipeline.config, "whisper_model",
                               lambda c: pathlib.Path("/bin/true")), \
             mock.patch.object(pipeline.subprocess, "run", fake_run):
            out = pipeline.transcribe(wav, cfg)
        self.assertIn("--prompt", calls["argv"])
        self.assertIn("Omarchy, Wisp", calls["argv"])
        self.assertEqual(out, "hello omarchy")
