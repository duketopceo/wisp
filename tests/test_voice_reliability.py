#!/usr/bin/env python3
"""Voice input reliability: toggle press, silence auto-stop, short STT
prompt, garbage-transcript guard, modest capability copy."""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import endpoint, garbage, pipeline, stage_capture, stage_speak  # noqa: E402
from wisp import vocab  # noqa: E402

GOOD = "show me what you can do"
BAD = ("What's your setup? of 1st, per, juta, rr. what's your setup "
       "kentra. kuzulu chat, hdsc.com. ddp, kdenlive, kdenlive, kdenlive, "
       "kdenlive, kdenlive. kdenlive. HWMVL's host, gpu screen recorder, "
       "dc1.jbf.")


def _wispd():
    path = str(ROOT / "wispd")
    loader = importlib.machinery.SourceFileLoader("wispd_vr", path)
    spec = importlib.util.spec_from_loader("wispd_vr", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class SilenceEndpointTest(unittest.TestCase):
    def _run(self, ep, levels, step=0.1):
        t = 0.0
        for lv in levels:
            if ep.feed(lv, t):
                return t
            t += step
        return None

    def test_fires_after_speech_then_silence(self):
        ep = endpoint.SilenceEndpoint(silence_s=2.0)
        at = self._run(ep, [0.5] * 10 + [0.0] * 40)
        self.assertIsNotNone(at)
        self.assertAlmostEqual(at, 1.0 + 2.0, delta=0.25)

    def test_never_fires_without_speech(self):
        ep = endpoint.SilenceEndpoint(silence_s=2.0)
        self.assertIsNone(self._run(ep, [0.0] * 200))

    def test_pause_shorter_than_limit_does_not_fire(self):
        ep = endpoint.SilenceEndpoint(silence_s=2.0)
        self.assertIsNone(self._run(ep, ([0.5] * 10 + [0.0] * 10) * 5))

    def test_continuous_noise_never_fires(self):
        ep = endpoint.SilenceEndpoint(silence_s=2.0)
        self.assertIsNone(self._run(ep, [0.4] * 600))

    def test_disabled_and_config(self):
        ep = endpoint.SilenceEndpoint(silence_s=0)
        self.assertIsNone(self._run(ep, [0.5] * 10 + [0.0] * 100))
        self.assertEqual(endpoint.silence_seconds({}), 2.5)
        self.assertEqual(endpoint.silence_seconds(
            {"audio": {"silence_s": "0"}}), 0.0)
        self.assertEqual(endpoint.silence_seconds(
            {"audio": {"silence_s": "x"}}), 2.5)

    def test_fires_once(self):
        ep = endpoint.SilenceEndpoint(silence_s=1.0)
        t = 0.0
        fired = 0
        for lv in [0.5] * 10 + [0.0] * 60:
            fired += ep.feed(lv, t)
            t += 0.1
        self.assertEqual(fired, 1)


class ListenToggleTest(unittest.TestCase):
    def setUp(self):
        self.w = _wispd()
        self.st = mock.Mock()
        self.ctl = {"stop": threading.Event(), "busy": threading.Event(),
                    "interrupt": threading.Event(),
                    "choice_event": threading.Event(), "choice_pick": "",
                    "rec": None, "rec_lock": threading.Lock()}
        raw = self.w._handler(self.st, {}, self.ctl)
        self.handle = lambda cmd: raw(cmd, {"pid": 1, "uid": 0})

    def _patches(self, stopped):
        def fake_run(st, cfg, ctl, wav=None, spans=None, turn_id=None):
            stopped.append(wav)
            ctl["busy"].clear()
        return [mock.patch.object(self.w.pipeline, "record_stop",
                                  return_value="x.wav"),
                mock.patch.object(self.w.speech, "stop"),
                mock.patch.object(self.w, "_run_listen", fake_run),
                mock.patch.object(self.w, "dlog")]

    def test_second_start_press_stops_and_submits(self):
        rec = {"proc": mock.Mock(), "sampler_stop": mock.Mock(),
               "t0": time.monotonic() - 5}
        self.ctl["rec"] = rec
        stopped = []
        ps = self._patches(stopped)
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        r = self.handle({"cmd": "listen", "phase": "start"})
        self.assertTrue(r["ok"])
        self.assertTrue(r.get("stopped"))
        self.assertIsNone(self.ctl["rec"])
        for _ in range(100):
            if stopped:
                break
            time.sleep(0.01)
        self.assertEqual(stopped, ["x.wav"])

    def test_bounce_right_after_start_is_ignored(self):
        rec = {"proc": mock.Mock(), "sampler_stop": mock.Mock(),
               "t0": time.monotonic() - 0.2}
        self.ctl["rec"] = rec
        stopped = []
        for p in self._patches(stopped):
            p.start()
            self.addCleanup(p.stop)
        r = self.handle({"cmd": "listen", "phase": "start"})
        self.assertTrue(r.get("recording"))
        self.assertIs(self.ctl["rec"], rec)

    def test_hold_to_talk_release_still_stops(self):
        self.ctl["rec"] = {"proc": mock.Mock(), "sampler_stop": mock.Mock(),
                           "t0": time.monotonic() - 3}
        stopped = []
        for p in self._patches(stopped):
            p.start()
            self.addCleanup(p.stop)
        r = self.handle({"cmd": "listen", "phase": "stop"})
        self.assertTrue(r.get("stopped"))

    def test_silence_stop_only_for_the_live_capture(self):
        ev = object()
        self.ctl["rec"] = {"sampler_stop": ev, "t0": 0}
        with mock.patch.object(self.w, "_rec_watchdog") as wd, \
                mock.patch.object(self.w, "dlog"):
            self.w._silence_stop(self.ctl, object())     # stale capture
            wd.assert_not_called()
            self.w._silence_stop(self.ctl, ev)
            wd.assert_called_once_with(self.ctl, 0)
            self.ctl["rec"] = None
            wd.reset_mock()
            self.w._silence_stop(self.ctl, ev)
            wd.assert_not_called()

    def test_first_press_wires_silence_stop_and_hard_cap(self):
        seen = {}

        def fake_start(state=None, on_silence=None, silence_s=0.0):
            seen.update(on_silence=on_silence, silence_s=silence_s)
            return {"proc": mock.Mock(), "sampler_stop": mock.Mock(),
                    "t0": time.monotonic()}
        for p in [mock.patch.object(self.w.pipeline, "record_start",
                                    fake_start),
                  mock.patch.object(self.w.speech, "stop"),
                  mock.patch.object(self.w, "_rec_watchdog") ,
                  mock.patch.object(self.w, "dlog")]:
            p.start()
            self.addCleanup(p.stop)
        self.assertTrue(self.handle({"cmd": "listen", "phase": "start"})["ok"])
        self.assertTrue(callable(seen["on_silence"]))
        self.assertGreater(seen["silence_s"], 0)


class VocabPromptTest(unittest.TestCase):
    def _build(self, cfg, activity=(), focused="kdenlive"):
        d = pathlib.Path(tempfile.mkdtemp())
        act = d / "activity.jsonl"
        act.write_text("\n".join(json.dumps({"window": {"app": a}})
                                 for a in activity))
        harness = d / "harness.json"
        harness.write_text(json.dumps(
            {"apps": {f"app{i}": {} for i in range(300)}}))
        with mock.patch.object(vocab, "ACTIVITY", act), \
                mock.patch.object(vocab, "CACHE", d / "v.txt"), \
                mock.patch("wisp.platform.active_window",
                           return_value={"app": focused}):
            return vocab.build(cfg)

    def test_short_list_never_the_app_inventory(self):
        out = self._build({"stt": {}}, ["steam"] * 5 + ["discord"] * 3
                          + [f"junk{i}" for i in range(40)])
        terms = [t.strip() for t in out.split(",")]
        self.assertLessEqual(len(terms), vocab._MAX_TERMS)
        self.assertLessEqual(len(out), vocab._MAX_CHARS)
        self.assertNotIn("app7", out)
        low = [t.lower() for t in terms]
        for core in ("wisp", "omarchy", "hyprland", "openrouter"):
            self.assertIn(core, low)
        self.assertIn("kdenlive", low)       # focused app, once
        self.assertEqual(low.count("kdenlive"), 1)
        self.assertIn("steam", low)          # most used
        self.assertNotIn("junk3", low)

    def test_static_prompt_kept_and_vocab_off_is_static_only(self):
        out = self._build({"stt": {"prompt": "Zorblax, Jev"}})
        self.assertTrue(out.startswith("Zorblax, Jev"))
        self.assertEqual(self._build({"stt": {"prompt": "S",
                                              "vocab_dynamic": "false"}}),
                         "S")

    def test_hosted_provider_sends_the_short_prompt(self):
        cap = {}

        class Resp:
            def read(self):
                return b'{"text": "hello"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        def fake(req, timeout=None):
            cap["body"] = req.data
            return Resp()
        wav = pathlib.Path(tempfile.mkdtemp()) / "a.wav"
        wav.write_bytes(b"RIFFfake")
        with mock.patch.object(vocab, "collect",
                               return_value=["Wisp", "Omarchy"]), \
                mock.patch.dict("os.environ", {"GROQ_API_KEY": "k"}), \
                mock.patch.object(vocab, "CACHE",
                                  pathlib.Path(tempfile.mkdtemp()) / "v"), \
                mock.patch.object(stage_capture._cancel, "urlopen", fake):
            pipeline.transcribe(wav, {"stt": {"provider": "openai"}})
        self.assertIn(b"Wisp, Omarchy", cap["body"])


class GarbageGuardTest(unittest.TestCase):
    PROMPT = "Wisp, Omarchy, Hyprland, kdenlive, gpu screen recorder"

    def test_real_good_transcript_passes(self):
        self.assertEqual(
            garbage.looks_like_garbage(GOOD, self.PROMPT, 2.0), "")

    def test_real_bad_transcript_rejected(self):
        self.assertEqual(
            garbage.looks_like_garbage(BAD, self.PROMPT, 45.0), "repeat")

    def test_prompt_echo(self):
        self.assertEqual(garbage.looks_like_garbage(
            "Wisp Omarchy Hyprland kdenlive gpu screen recorder",
            self.PROMPT, 3.0), "prompt_echo")

    def test_sparse_long_clip(self):
        self.assertEqual(garbage.looks_like_garbage(
            "okay then", "", 20.0), "sparse")
        self.assertEqual(garbage.looks_like_garbage(
            "okay then", "", 3.0), "")

    def test_ordinary_commands_pass(self):
        for t in ("open Omarchy settings", "what is on my screen",
                  "that is very very good", "tell me about Hyprland"):
            self.assertEqual(
                garbage.looks_like_garbage(t, self.PROMPT, 3.0), "", t)

    def test_empty_is_not_garbage(self):
        self.assertEqual(garbage.looks_like_garbage("", self.PROMPT, 3), "")

    def _ctx(self, wav):
        state = mock.Mock()
        sp = mock.Mock()
        sp.ms = {"record": 0, "stt": 0}
        return SimpleNamespace(
            typed="", wav=wav, state=state, sp=sp, token=mock.Mock(),
            cfg={"stt": {}}, turn="t1", lang="", text="")

    def test_capture_stage_says_didnt_catch_that_and_stops(self):
        wav = pathlib.Path(tempfile.mkdtemp()) / "a.wav"
        wav.write_bytes(b"x")
        ctx = self._ctx(wav)
        with mock.patch.object(pipeline, "transcribe", return_value=BAD), \
                mock.patch.object(pipeline, "notify"), \
                mock.patch("wisp.speech.speak") as speak:
            ok = stage_capture.capture_stage(ctx)
        self.assertFalse(ok)
        ctx.state.transition.assert_called_with("done",
                                                result=garbage.REPLY)
        speak.assert_called_once()
        self.assertEqual(garbage.REPLY, "I didn't catch that")

    def test_capture_stage_lets_the_good_transcript_through(self):
        wav = pathlib.Path(tempfile.mkdtemp()) / "a.wav"
        wav.write_bytes(b"x")
        ctx = self._ctx(wav)
        with mock.patch.object(pipeline, "transcribe", return_value=GOOD):
            self.assertTrue(stage_capture.capture_stage(ctx))
        self.assertEqual(ctx.text, GOOD)


class PersonaCopyTest(unittest.TestCase):
    def test_persona_makes_no_file_or_cli_access_claim(self):
        low = stage_speak.PERSONA.lower()
        # every mention of these must be inside a refusal
        for word in ("file", "terminal", "command line", "system settings"):
            if word in low:
                self.assertIn("never claim access", low)
        for claim in ("direct access", "full access", "run commands",
                      "control your system"):
            self.assertNotIn(claim, low)

    def test_persona_names_what_wisp_does(self):
        low = stage_speak.PERSONA.lower()
        for word in ("screen", "point", "confirm"):
            self.assertIn(word, low)


if __name__ == "__main__":
    unittest.main()
