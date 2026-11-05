#!/usr/bin/env python3
"""U12: key-down warm-up, and the fast / teach model split. Fakes only: no
DNS, audio device, network or model call."""
import pathlib
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from wisp import brain, pipeline, speech, stage_capture, stage_speak  # noqa: E402
from wisp import walkthrough_run as wr  # noqa: E402
from wisp import telemetry, warm  # noqa: E402
from harness import latency as hl, runner  # noqa: E402

import test_stage_speak  # noqa: E402

CFG = {"voice": {"enabled": "true"},
       "stt": {"base_url": "https://stt.example/v1"},
       "brain": {"default": "openrouter:vendor/default"}}


class FakeProc:
    def __init__(self):
        self.killed = False
        self._done = threading.Event()

    def poll(self):
        return 0 if self._done.is_set() else None

    def wait(self, timeout=None):
        self._done.wait(timeout)

    def kill(self):
        self.killed = True
        self._done.set()


class Rig:
    """Counts resolver and player calls without touching the system."""

    def __init__(self, fail=False):
        self.resolved, self.procs, self.fail = [], [], fail

    def resolve(self, host):
        if self.fail:
            raise OSError("no network")
        self.resolved.append(host)

    def spawn(self, argv):
        p = FakeProc()
        self.procs.append((argv, p))
        return p

    def kw(self):
        return {"resolve": self.resolve, "spawn": self.spawn,
                "player": lambda path: ["play", path]}


def warm_threads():
    return [t for t in threading.enumerate() if t.name == "wisp-warm"]


class WarmPath(unittest.TestCase):
    def setUp(self):
        warm.discard()
        self.addCleanup(warm.discard)
        p = mock.patch.object(speech, "voice_enabled", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_key_down_starts_one_warm_up_and_key_up_reuses_it(self):
        rig = Rig()
        w = warm.begin(CFG, **rig.kw())
        self.assertIsNotNone(w)
        w.join()
        self.assertEqual(sorted(rig.resolved), sorted(set(rig.resolved)))
        self.assertIn("stt.example", rig.resolved)
        self.assertEqual(len(rig.procs), 1)          # one silent clip
        self.assertTrue(w.woke)
        self.assertIs(warm.claim(), w)               # key-up: the same one
        self.addCleanup(w.close)
        self.assertTrue(w.claimed)
        self.assertIsNone(warm.claim())              # claimed once
        self.assertEqual(len(rig.procs), 1)          # nothing restarted

    def test_a_second_press_replaces_an_unclaimed_warm_up(self):
        a = warm.begin(CFG, **Rig().kw())
        b = warm.begin(CFG, **Rig().kw())
        self.assertIsNot(a, b)
        self.assertFalse(a._thread.is_alive())
        self.assertIs(warm.claim(), b)
        b.close()

    def test_a_cancelled_press_releases_resources_and_leaks_no_thread(self):
        rig = Rig()
        w = warm.begin(CFG, **rig.kw())
        for _ in range(100):                        # the clip is playing
            if rig.procs:
                break
            time.sleep(0.01)
        warm.discard()
        self.assertFalse(w._thread.is_alive())
        self.assertEqual(warm_threads(), [])
        self.assertTrue(all(p.poll() is not None for _, p in rig.procs))
        self.assertEqual(w._tmp, "")                 # temp WAV removed
        self.assertIsNone(warm.claim())

    def test_a_failing_warm_up_degrades_to_the_cold_path(self):
        rig = Rig(fail=True)
        w = warm.begin(CFG, **rig.kw())
        w.join()
        self.assertEqual(rig.resolved, [])           # nothing raised
        w.close()
        spawn_boom = Rig()
        spawn_boom.spawn = mock.Mock(side_effect=OSError("no player"))
        w2 = warm.begin(CFG, **spawn_boom.kw())
        w2.join()
        self.assertFalse(w2.woke)

    def test_off_means_no_thread(self):
        cfg = {**CFG, "voice": {"enabled": "true", "warm": "false"}}
        self.assertIsNone(warm.begin(cfg, **Rig().kw()))
        self.assertEqual(warm_threads(), [])

    def test_voice_off_skips_the_audio_wake_but_still_resolves(self):
        rig = Rig()
        with mock.patch.object(speech, "voice_enabled", return_value=False):
            w = warm.begin(CFG, **rig.kw())
            w.join()
        self.assertEqual(rig.procs, [])
        self.assertIn("stt.example", rig.resolved)

    def test_cancelled_recording_discards_the_warm_up(self):
        with mock.patch.object(warm, "discard") as d:
            stage_capture._record_discard({"out": None})
        d.assert_called_once()


class ModelSplit(unittest.TestCase):
    def test_unset_keeps_the_exact_config_object(self):
        for role in ("fast", "teach"):
            self.assertIs(brain.with_role(CFG, role), CFG)
            self.assertEqual(brain.role_model(CFG, role), "")

    def test_set_swaps_only_the_primary_openrouter_model(self):
        cfg = {"brain": {"default": "openrouter:vendor/default",
                         "fallback": "ollama:x",
                         "fast_model": " vendor/small ",
                         "teach_model": "vendor/large"}}
        fast = brain.with_role(cfg, "fast")
        self.assertEqual(brain.provider(fast)["model"], "vendor/small")
        self.assertEqual(brain.provider(brain.with_role(cfg, "teach"))
                         ["model"], "vendor/large")
        self.assertEqual(brain.provider(cfg)["model"], "vendor/default")
        self.assertEqual(brain.chain(fast)[1]["name"], "ollama")

    def test_a_non_openrouter_primary_is_left_alone(self):
        cfg = {"brain": {"default": "ollama:local", "fast_model": "v/s"}}
        self.assertIs(brain.with_role(cfg, "fast"), cfg)

    def test_unknown_role_is_ignored(self):
        self.assertEqual(brain.role_model(CFG, "deep"), "")

    def test_plan_uses_the_teach_model_and_answer_lane_the_fast_model(self):
        cfg = {"brain": {"default": "openrouter:vendor/default",
                         "fast_model": "vendor/small",
                         "teach_model": "vendor/large"}}
        seen = {}

        def chat(messages, cfg_, timeout=0):
            seen["plan"] = brain.provider(cfg_)["model"]
            return {"content": '{"steps":[{"say":"go"}]}'}
        wr.plan("do it", cfg, chat=chat)
        self.assertEqual(seen["plan"], "vendor/large")


class AnswerLane(test_stage_speak.StageBase):
    def run_with(self, cfg):
        got = {}

        def ask(text, cfg_, session_text="", image_b64=None,
                on_delta=None, meta=None):
            got["cfg"] = cfg_
            return "It is noon."
        ctx = self.ctx(cfg)
        with mock.patch.object(pipeline, "ask_chat", side_effect=ask), \
             mock.patch.object(pipeline.speech, "speak", return_value=None):
            stage_speak._answer(ctx)
        return got["cfg"]

    def test_a_quick_ask_goes_to_the_fast_model_when_set(self):
        cfg = {"brain": {"default": "openrouter:vendor/default",
                         "fast_model": "vendor/small"}}
        got = self.run_with(cfg)
        self.assertEqual(brain.provider(got)["model"], "vendor/small")

    def test_unset_changes_nothing(self):
        cfg = {"brain": {"default": "openrouter:vendor/default"}}
        self.assertIs(self.run_with(cfg), cfg)


class ReplayComposite(unittest.TestCase):
    def test_the_replayed_composite_is_not_worse_than_the_u11_baseline(self):
        base = telemetry.load_baseline()["paths"]["FV"]
        got = [hl.samples(runner.run_turn("answer_points_timed"))["FV"]
               for _ in range(3)]
        # the baseline is fakes only, so this bounds code overhead; the
        # slack covers a loaded runner, not a regression
        self.assertLessEqual(sorted(got)[1], base["p90"] * 3 + 250, got)


if __name__ == "__main__":
    unittest.main()
