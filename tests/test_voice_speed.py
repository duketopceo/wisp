"""B8: voice speed 0.5 to 1.5x and the spoken "talk slower" commands."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import (config, cua_safety, platform, speech,  # noqa: E402
                  stage_execute, stage_route, voice_settings)

WORDS = "the quick brown fox jumps over the lazy dog again and again today"


def seconds(argv, text=WORDS):
    """How long espeak would take: words / (words per minute)."""
    wpm = int(argv[argv.index("-s") + 1]) if "-s" in argv else \
        platform.ESPEAK_WPM
    return len(text.split()) / wpm * 60


def cfg(speed=None, cmd=""):
    v = {"enabled": "true", "cmd": cmd}
    if speed is not None:
        v["speed"] = speed
    return {"voice": v}


class Speed(unittest.TestCase):
    def test_parse_and_clamp(self):
        self.assertEqual(speech.speed({}), 1.0)
        self.assertEqual(speech.speed(cfg("1.25")), 1.25)
        self.assertEqual(speech.speed(cfg("9")), 1.5)
        self.assertEqual(speech.speed(cfg("0.1")), 0.5)
        for bad in ("fast", "nan", "", "  "):
            self.assertEqual(speech.speed(cfg(bad)), 1.0, bad)

    def espeak(self, c):
        with mock.patch.object(platform, "tts_binary",
                               return_value="espeak-ng"):
            return speech._argv(c)

    def test_normal_speed_adds_no_flag(self):
        self.assertEqual(self.espeak(cfg("1.0")), ["espeak-ng", "--stdin"])
        self.assertEqual(self.espeak(cfg()), ["espeak-ng", "--stdin"])

    def test_1_5x_shortens_the_utterance_by_at_least_a_quarter(self):
        base = seconds(self.espeak(cfg()))
        fast = self.espeak(cfg("1.5"))
        self.assertEqual(fast[:3], ["espeak-ng", "-s", "262"])
        self.assertLessEqual(seconds(fast), base * 0.75)

    def test_half_speed_lengthens_it_by_at_least_half_again(self):
        base = seconds(self.espeak(cfg()))
        slow = self.espeak(cfg("0.5"))
        self.assertEqual(slow[:3], ["espeak-ng", "-s", "88"])
        self.assertGreaterEqual(seconds(slow), base * 1.5)

    def test_a_custom_command_receives_the_rate(self):
        c = cfg("0.75", cmd="say --rate {rate} {text}")
        self.assertEqual(speech._argv(c), ["say", "--rate", "0.75"])
        c = cfg(None, cmd="say --rate {rate} {text}")
        self.assertEqual(speech._argv(c), ["say", "--rate", "1"])

    def test_the_text_placeholder_is_dropped_from_argv(self):
        c = cfg("1.5", cmd="say {text}")
        self.assertEqual(speech._argv(c), ["say"])

    def test_streamed_sentences_use_the_same_rate(self):
        seen = []

        class P:
            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        c = cfg("1.25", cmd="say {rate} {text}")
        # Groq is the default voice provider; resolving its key shells out
        # to omaseal through the (mocked) Popen below. This test is about
        # the local command's rate, so keep the Groq path out of it.
        from wisp import tts_groq
        with mock.patch.object(tts_groq, "usable", return_value=False), \
                mock.patch.object(speech.subprocess, "Popen",
                                  side_effect=lambda argv, **kw:
                                  seen.append(argv) or P()):
            sp = speech.SentenceSpeaker(c)
            sp.finish("One. Two.")
            sp._worker.join(timeout=5)
        self.assertEqual(seen, [["say", "1.25"], ["say", "1.25"]])


class Intent(unittest.TestCase):
    def test_phrases(self):
        for said, kind in (("talk slower", "slower"),
                           ("Wisp, please speak a bit slower.", "slower"),
                           ("slow down", "slower"),
                           ("talk faster", "faster"),
                           ("speed up", "faster"),
                           ("talk at normal speed", "normal"),
                           ("normal speed", "normal")):
            self.assertEqual(voice_settings.intent(said), kind, said)

    def test_ordinary_speech_is_left_alone(self):
        for said in ("slow down the video", "how do I speed up my laptop",
                     "talk to bob", "open firefox", ""):
            self.assertIsNone(voice_settings.intent(said), said)

    def test_routes_before_any_model(self):
        self.assertEqual(stage_route.fixed_route("talk slower", "act"),
                         ("setting", "voice-speed:slower"))
        self.assertEqual(stage_route.fixed_route("talk slower", "chat"),
                         ("setting", "voice-speed:slower"))


class Apply(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        self.audit = self.dir / "cua.jsonl"
        self.saved = []
        for target, val in (
                (config, ("set_config", lambda s, k, v:
                          self.saved.append((s, k, v)))),
                (cua_safety, ("audit_default_path", lambda: self.audit))):
            p = mock.patch.object(target, *val)
            p.start()
            self.addCleanup(p.stop)

    def test_slower_steps_down_goes_through_set_config_and_is_audited(self):
        c = cfg("1.0")
        out = voice_settings.apply("slower", c, turn="t1")
        self.assertEqual(out, "ACTED (0 steps): okay, talking slower.")
        self.assertEqual(self.saved, [("voice", "speed", "0.75")])
        self.assertEqual(c["voice"]["speed"], "0.75")     # live cfg too
        rec = json.loads(self.audit.read_text().splitlines()[0])
        self.assertEqual((rec["tool"], rec["setting"], rec["value"],
                          rec["turn"]), ("config", "voice.speed", "0.75",
                                         "t1"))

    def test_faster_and_normal(self):
        c = cfg("1.0")
        voice_settings.apply("faster", c)
        self.assertEqual(c["voice"]["speed"], "1.25")
        voice_settings.apply("normal", c)
        self.assertEqual(c["voice"]["speed"], "1")
        self.assertEqual([v for *_, v in self.saved], ["1.25", "1"])

    def test_the_ends_of_the_range_say_so_and_change_nothing(self):
        out = voice_settings.apply("slower", cfg("0.5"))
        self.assertIn("as slow as I go", out)
        out = voice_settings.apply("faster", cfg("1.5"))
        self.assertIn("as fast as I go", out)
        self.assertEqual(self.saved, [])
        self.assertFalse(self.audit.exists())

    def test_an_off_step_value_snaps_to_the_nearest_step(self):
        c = cfg("1.1")
        voice_settings.apply("slower", c)
        self.assertEqual(c["voice"]["speed"], "0.75")

    def test_audit_can_be_turned_off(self):
        with mock.patch.object(cua_safety, "settings",
                               return_value={"audit": False}):
            voice_settings.apply("slower", cfg("1.0"))
        self.assertFalse(self.audit.exists())

    def test_a_refused_write_is_reported_not_applied(self):
        with mock.patch.object(config, "set_config",
                               side_effect=ValueError("bad")):
            c = cfg("1.0")
            out = voice_settings.apply("slower", c)
        self.assertTrue(out.startswith("SKIP"))
        self.assertEqual(c["voice"]["speed"], "1.0")

    def test_execute_runs_it_and_the_reply_is_spoken(self):
        c = cfg("1.0")
        out = stage_execute.execute({"route": {"choice": "setting"}}, c,
                                    detail="voice-speed:slower",
                                    initial_image=None,
                                    interrupted=lambda: False)
        self.assertEqual(out, "ACTED (0 steps): okay, talking slower.")


if __name__ == "__main__":
    unittest.main()
