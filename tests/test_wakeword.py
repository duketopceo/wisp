"""B33: the optional local wake word. Off by default, deaf to wisp's own
voice, refuses open speakers, and only takes a turn after the phrase."""
import array
import math
import pathlib
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import config, echo_cancel, wakeword as ww  # noqa: E402


def tone(chunks, amp=4000):
    """`chunks` 100 ms of loud 'speech' (a 220 Hz tone)."""
    out = bytearray()
    n = ww.CHUNK_BYTES // 2
    for c in range(chunks):
        a = array.array("h", (int(amp * math.sin(2 * math.pi * 220 * (c * n + i) / ww.RATE))
                              for i in range(n)))
        out += a.tobytes()
    return bytes(out)


def hush(chunks):
    return bytes(ww.CHUNK_BYTES) * chunks


def chunks_of(pcm):
    return [pcm[i:i + ww.CHUNK_BYTES] for i in range(0, len(pcm), ww.CHUNK_BYTES)]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        self.t += 0.1
        return self.t


class Defaults(unittest.TestCase):
    def test_off_by_default_and_in_the_shipped_config(self):
        self.assertFalse(ww.enabled({}))
        self.assertFalse(ww.enabled({"wakeword": {"enabled": "false"}}))
        self.assertTrue(ww.enabled({"wakeword": {"enabled": "true"}}))
        self.assertIn("[wakeword]\n", config.DEFAULT_CONFIG)
        self.assertIn("[wakeword]", config.DEFAULT_CONFIG)

    def test_the_plan_says_what_is_listened_to_and_where_audio_goes(self):
        text = ww.plan({})
        for must in ("hey wisp", "stays on this machine", "local whisper.cpp",
                     "no screenshot", "open-mic", "Holding the key"):
            self.assertIn(must, text)

    def test_phrase_matching(self):
        self.assertTrue(ww.matches("Hey, Wisp!", "hey wisp"))
        self.assertTrue(ww.matches("okay hey wisp what is this", "hey wisp"))
        self.assertFalse(ww.matches("hey wasp", "hey wisp"))
        self.assertFalse(ww.matches("", "hey wisp"))


class Detect(unittest.TestCase):
    def detector(self, says, speaking=lambda: False):
        calls = []

        def transcribe(pcm):
            calls.append(len(pcm))
            return says
        return ww.Detector(transcribe, speaking, "hey wisp", clock=Clock()), calls

    def run_pcm(self, det, pcm):
        return [det.feed(c) for c in chunks_of(pcm)]

    def test_the_phrase_fires_once_the_speaker_pauses(self):
        det, calls = self.detector("hey wisp")
        got = self.run_pcm(det, hush(5) + tone(8) + hush(8))
        self.assertEqual(got.count(True), 1)
        self.assertEqual(len(calls), 1)

    def test_other_speech_is_checked_but_does_not_fire(self):
        det, calls = self.detector("what time is the standup")
        got = self.run_pcm(det, tone(8) + hush(8))
        self.assertNotIn(True, got)
        self.assertEqual(len(calls), 1)

    def test_silence_is_never_transcribed(self):
        det, calls = self.detector("hey wisp")
        self.run_pcm(det, hush(80))
        self.assertEqual(calls, [])

    def test_a_click_is_not_speech(self):
        det, calls = self.detector("hey wisp")
        self.run_pcm(det, tone(1) + hush(10))
        self.assertEqual(calls, [])

    def test_wisps_own_voice_does_not_trigger_it(self):
        # fixture: a recording of wisp speaking the phrase; the speaking flag
        # is up while it plays and the tail covers the echo after it
        speaking = {"on": True}
        det, calls = self.detector("hey wisp", lambda: speaking["on"])
        own = tone(20) + hush(8)
        got = self.run_pcm(det, own)
        self.assertNotIn(True, got)
        self.assertEqual(calls, [], "never even sent to the model")
        speaking["on"] = False
        got = self.run_pcm(det, tone(8) + hush(2))      # still in the tail
        self.assertNotIn(True, got)
        self.assertEqual(calls, [])

    def test_it_hears_again_after_the_tail(self):
        det, calls = self.detector("hey wisp")
        got = self.run_pcm(det, tone(8) + hush(8))
        self.assertTrue(got.count(True) == 1)

    def test_a_failing_model_never_fires(self):
        def boom(pcm):
            raise RuntimeError("no model")
        det = ww.Detector(boom, lambda: False, "hey wisp", clock=Clock())
        self.assertNotIn(True, self.run_pcm(det, tone(8) + hush(8)))

    def test_local_transcribe_without_a_model_is_silent_not_cloud(self):
        cfg = {"audio": {"whisper_model": "nope.bin"}, "stt": {"provider": "openai"}}
        self.assertEqual(ww.local_transcribe(cfg)(tone(3)), "")


class Refuses(unittest.TestCase):
    def runner(self, modules="", sinks="", default=""):
        def run(argv):
            if argv[:3] == ["pactl", "list", "modules"]:
                return modules
            if argv[:3] == ["pactl", "list", "sinks"]:
                return sinks
            if argv[:2] == ["pactl", "get-default-sink"]:
                return default
            return ""
        return run

    SPEAKER = ("Sink #1\n\tName: spk\n\tActive Port: analog-output-speaker\n")
    PHONES = ("Sink #2\n\tName: hp\n\tActive Port: analog-output-headphones\n")

    def test_open_speakers_are_refused_with_the_fix_named(self):
        ok, why = ww.can_enable({}, self.runner(sinks=self.SPEAKER, default="spk"))
        self.assertFalse(ok)
        self.assertIn("--echo-cancel", why)

    def test_unknown_output_counts_as_open(self):
        self.assertFalse(ww.can_enable({}, self.runner())[0])

    def test_headphones_are_fine(self):
        self.assertEqual(ww.can_enable({}, self.runner(
            sinks=self.SPEAKER + self.PHONES, default="hp")), (True, "headphones"))

    def test_echo_cancel_module_is_fine(self):
        self.assertEqual(ww.can_enable({}, self.runner(
            modules="31\tlibpipewire-module-echo-cancel\n",
            sinks=self.SPEAKER, default="spk")), (True, "echo-cancel"))

    def test_enabling_the_setting_is_refused_over_speakers(self):
        orig = ww.can_enable
        ww.can_enable = lambda cfg=None, runner=None: (False, "open speakers")
        try:
            with self.assertRaises(ValueError) as cm:
                config.set_config("wakeword", "enabled", "true")
            self.assertIn("stays off", str(cm.exception))
        finally:
            ww.can_enable = orig


class Pipeline(unittest.TestCase):
    class Stream:
        def __init__(self, pcm):
            self.chunks = chunks_of(pcm)
            self.closed = False

        def read(self, n):
            return self.chunks.pop(0) if self.chunks else b""

        def close(self):
            self.closed = True

    def listener(self, pcm, says="hey wisp", cfg=None):
        cfg = cfg or {"wakeword": {"enabled": "true"}}
        sent, mic = [], []
        lis = ww.Listener(cfg, sent.append, mic.append,
                          lambda: self.Stream(pcm), lambda: False,
                          transcribe=lambda p: says, log=lambda s: None)
        lis.det.clock = Clock()
        return lis, sent, mic

    def test_phrase_starts_a_turn_and_silence_ends_it(self):
        pcm = hush(3) + tone(6) + hush(8) + tone(10) + hush(14) + hush(5)
        lis, sent, mic = self.listener(pcm)
        lis.run()
        self.assertEqual(sent, ["start", "stop"])
        self.assertEqual(mic, ["open", ""], "mic mark up, then cleared")

    def test_no_phrase_means_no_turn_and_no_start(self):
        pcm = hush(3) + tone(6) + hush(8)
        lis, sent, mic = self.listener(pcm, says="lunch?")
        lis.run()
        self.assertEqual(sent, [])
        self.assertEqual(mic, ["open", ""])

    def test_turning_it_off_ends_the_listener(self):
        cfg = {"wakeword": {"enabled": "false"}}
        lis, sent, mic = self.listener(tone(50), cfg=cfg)
        lis.run()
        self.assertEqual(sent, [])

    def test_the_supervisor_runs_nothing_while_it_is_off(self):
        cfg, stop, started = {}, threading.Event(), []
        t = threading.Thread(target=ww.supervise, args=(
            cfg, lambda v: None, lambda p: None, lambda: False),
            kwargs={"stop": stop, "poll_s": 0.01,
                    "can": lambda c: started.append("checked") or (True, "x"),
                    "open_stream": lambda: self.Stream(b"")})
        t.start()
        stop.wait(0.15)
        stop.set()
        t.join(2)
        self.assertEqual(started, [], "not even the speaker check ran")


class EchoCancel(unittest.TestCase):
    def test_plan_then_write_touches_one_file(self):
        home = pathlib.Path(tempfile.mkdtemp())
        self.assertIn("creates", echo_cancel.plan(home))
        self.assertFalse(echo_cancel.path(home).exists())
        f = echo_cancel.write(home)
        self.assertEqual(f.name, "60-wisp-echo-cancel.conf")
        self.assertIn("echo-cancel", f.read_text())
        self.assertEqual([p for p in home.rglob("*") if p.is_file()], [f])
        self.assertIn("replaces", echo_cancel.plan(home))


if __name__ == "__main__":
    unittest.main()
