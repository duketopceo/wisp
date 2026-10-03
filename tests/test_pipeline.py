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


class TurnSpansTest(unittest.TestCase):
    """U1: run_listen records stage spans named after the latency
    budget paths; Jev time no longer includes context-gathering time."""

    def _run(self, spans=None, shot_s=0.2, jev_s=0.05, route="answer"):
        import tempfile
        import time
        from unittest import mock
        from wisp import trace
        d = pathlib.Path(tempfile.mkdtemp())
        tf = d / "trace.jsonl"
        logged = {}
        st = mock.Mock()
        st.transition = lambda s, **kw: None

        def slow_shot():
            time.sleep(shot_s)
            return None

        def slow_jev(*a, **k):
            time.sleep(jev_s)
            return {"answers": {"route": {"choice": route},
                                "confidence": {"score": 0.9},
                                "app": {"choice": ""}}}
        cfg = {"audio": {"seconds": "0"}, "agent": {}}
        from wisp import session as sess  # noqa: F811
        from wisp import memory as mem  # noqa: F811
        with mock.patch.object(trace, "TRACE_FILE", tf), \
             mock.patch.object(pipeline, "record",
                               return_value=d / "x.wav"), \
             mock.patch.object(pipeline, "transcribe", return_value="hello"), \
             mock.patch.object(pipeline, "capture_screen", slow_shot), \
             mock.patch.object(pipeline, "ask_jev", slow_jev), \
             mock.patch.object(pipeline, "execute", return_value="ANSWERED"), \
             mock.patch.object(pipeline, "ask_chat", return_value="hi"), \
             mock.patch.object(pipeline, "build_questions", return_value={}), \
             mock.patch.object(pipeline, "active_window", return_value={}), \
             mock.patch.object(pipeline, "notify"), \
             mock.patch.object(pipeline.speech, "speak", return_value=None), \
             mock.patch.object(mem, "context_block", return_value=""), \
             mock.patch.object(sess, "append_turn"), \
             mock.patch.object(sess, "tail", return_value=[]), \
             mock.patch.object(sess, "as_text", return_value=""), \
             mock.patch.object(pipeline, "log_decision",
                               side_effect=lambda r: logged.update(r)):
            trace.reset_cache()
            kw = {"spans": spans} if spans is not None else {}
            rc = pipeline.run_listen(cfg, st, wav=d / "x.wav", **kw)
            evs = trace.read(tf, kind="span", tail=100)
            trace.reset_cache()
        self.assertEqual(rc, 0)
        return logged, {e["step"]: e for e in evs}

    def test_route_excludes_screenshot_time(self):
        logged, spans = self._run(shot_s=0.2, jev_s=0.05)
        self.assertGreaterEqual(spans["screenshot"]["ms"], 190)
        self.assertGreaterEqual(spans["context"]["ms"], 190)
        self.assertLess(spans["context"]["ms"], 400)
        self.assertGreaterEqual(spans["route"]["ms"], 45)
        self.assertLess(spans["route"]["ms"], 150)

    def test_all_named_spans_present_on_answer_path(self):
        _, spans = self._run()
        for name in ("stt", "context", "route", "done", "screenshot",
                     "hyprctl", "memory", "goal", "tts_start"):
            self.assertIn(name, spans)

    def test_legacy_keys_still_logged_and_derived(self):
        logged, spans = self._run()
        t = logged["timing_ms"]
        for k in ("record_ms", "stt_ms", "jev_ms", "act_ms"):
            self.assertIn(k, t)
        self.assertEqual(t["stt_ms"], spans["stt"]["ms"])
        self.assertEqual(t["jev_ms"], spans["context"]["ms"]
                         + spans["route"]["ms"])
        self.assertGreaterEqual(t["jev_ms"], 240)

    def test_supplied_spans_object_is_used(self):
        from wisp import trace
        sp = trace.Spans()
        sp.record("press", sp.t0)
        _, spans = self._run(spans=sp)
        self.assertIn("press", spans)
        self.assertEqual(spans["press"]["data"]["t0_source"], "daemon")
