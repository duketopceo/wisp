import pathlib
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

from wisp import platform, speech


def _proc():
    return speech._PROC


class SpeechTests(unittest.TestCase):
    def setUp(self):
        speech.stop()
        self.dir = tempfile.TemporaryDirectory()
        if sys.platform == "win32":
            self.script = f'"{sys.executable}" -c "import time; time.sleep(60)"'
        else:
            script = pathlib.Path(self.dir.name) / "tts.sh"
            script.write_text("#!/bin/sh\nsleep 60\n")
            script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
            self.script = str(script)

    def tearDown(self):
        speech.stop()
        self.dir.cleanup()

    def cfg(self, cmd=""):
        return {"voice": {"enabled": "true", "cmd": cmd}}

    def test_voice_disabled_no_spawn(self):
        speech.speak("hi", {"voice": {"enabled": "false"}})
        self.assertIsNone(_proc())

    def test_cmd_override_spawns_and_tracks(self):
        speech.speak("hi", self.cfg(self.script))
        self.assertIsNotNone(_proc())
        self.assertIsNone(_proc().poll())

    def test_barge_in_kills(self):
        speech.speak("hi", self.cfg(self.script))
        proc = _proc()
        speech.stop()
        proc.wait(timeout=5)
        self.assertIsNotNone(proc.returncode)
        self.assertIsNone(_proc())

    def test_new_speak_kills_old(self):
        speech.speak("one", self.cfg(self.script))
        first = _proc()
        speech.speak("two", self.cfg(self.script))
        self.assertIsNot(_proc(), first)
        first.wait(timeout=5)
        self.assertIsNotNone(first.returncode)

    def test_text_placeholder(self):
        out = pathlib.Path(self.dir.name) / "out.txt"
        if sys.platform == "win32":
            py_code = 'import sys, pathlib; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])'
            cmd = f'"{sys.executable}" -c "{py_code}" "{out}" {{text}}'
        else:
            script = pathlib.Path(self.dir.name) / "echo.sh"
            script.write_text(f'#!/bin/sh\necho "$(cat)" > {out}\n')
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            cmd = f"{script} {{text}}"
        speech.speak("hello world", self.cfg(cmd))
        for _ in range(50):
            if out.exists():
                break
            time.sleep(0.05)
        self.assertEqual(out.read_text().strip(), "hello world")

    def test_on_exit_fires_and_clears(self):
        import threading
        done = threading.Event()
        if sys.platform == "win32":
            cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
        else:
            script = pathlib.Path(self.dir.name) / "fast.sh"
            script.write_text("#!/bin/sh\nexit 0\n")
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            cmd = str(script)
        proc = speech.speak("hi", self.cfg(cmd))
        self.assertIsNotNone(proc)
        speech.on_exit(proc, done.set)
        self.assertTrue(done.wait(timeout=5))
        for _ in range(50):
            if _proc() is None:
                break
            time.sleep(0.05)
        self.assertIsNone(_proc())

    def test_no_binary_no_crash(self):
        # empty cmd + possibly missing espeak -> silent no-op
        speech.speak("hi", self.cfg("/nonexistent-bin-xyz"))
        self.assertIsNone(_proc())


class SentencePointsTests(unittest.TestCase):
    """SentenceSpeaker hands each sentence's points to on_sentence when the
    worker starts that sentence (before TTS spawns)."""

    def setUp(self):
        speech.stop()
        self.dir = tempfile.TemporaryDirectory()
        self.log = pathlib.Path(self.dir.name) / "spoken.txt"
        script = pathlib.Path(self.dir.name) / "tts.sh"
        script.write_text(f'#!/bin/sh\necho "$(cat)" >> {self.log}\nsleep 0.2\n')
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        self.script = str(script)
        self.calls = []

    def tearDown(self):
        speech.stop()
        self.dir.cleanup()

    def spoken_now(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def on_sentence(self, pts):
        self.calls.append((list(pts), self.spoken_now()))

    def speaker(self, cmd=None):
        cfg = {"voice": {"enabled": "true",
                         "cmd": self.script if cmd is None else cmd}}
        return speech.SentenceSpeaker(cfg, on_sentence=self.on_sentence)

    def wait_for(self, cond):
        for _ in range(100):
            if cond():
                return True
            time.sleep(0.05)
        return False

    def finish(self, sp, full, marks=()):
        import threading
        done = threading.Event()
        sp.finish(full, on_done=done.set, marks=marks)
        self.assertTrue(done.wait(timeout=10))

    def test_failing_callback_does_not_stall_the_speaker(self):
        # a raising on_sentence must not kill the worker: the rest of the
        # answer is still spoken and on_done still ends the turn
        def boom(pts):
            raise RuntimeError("callback bug")
        sp = speech.SentenceSpeaker(
            {"voice": {"enabled": "true", "cmd": self.script}},
            on_sentence=boom)
        text = "One here. Two there. "
        sp.feed(text, marks=[(3, {"x": 1, "y": 1})])
        self.finish(sp, text.strip())
        self.assertEqual(self.spoken_now(), ["One here.", "Two there."])

    TEXT = "One here. Two there."

    def test_points_fire_per_sentence_before_its_tts(self):
        sp = self.speaker()
        sp.feed(self.TEXT + " ", [(8, "p1"), (19, "p2")])
        self.finish(sp, self.TEXT, [(8, "p1"), (19, "p2")])
        self.assertEqual([c[0] for c in self.calls], [["p1"], ["p2"]])
        # p1 fired before any TTS ran, p2 after sentence one had spoken
        self.assertEqual(self.calls[0][1], [])
        self.assertEqual(self.calls[1][1], ["One here."])

    def test_mark_at_closing_offset_belongs_to_that_sentence(self):
        sp = self.speaker()
        # offset 9 == end of "One here." (before the space)
        self.finish(sp, self.TEXT, [(9, "p1")])
        self.assertEqual([c[0] for c in self.calls], [["p1"]])
        self.assertEqual(self.calls[0][1], [])

    def test_failed_spawn_still_fires_points(self):
        sp = self.speaker(cmd="/nonexistent-bin-xyz")
        self.finish(sp, self.TEXT, [(8, "p1"), (19, "p2")])
        self.assertEqual([c[0] for c in self.calls], [["p1"], ["p2"]])

    def test_trailing_marks_fire_with_tail(self):
        sp = self.speaker()
        sp.feed("One here. Two", [(8, "p1")])
        self.finish(sp, "One here. Two there", [(8, "p1"), (19, "p2")])
        self.assertEqual([c[0] for c in self.calls], [["p1"], ["p2"]])
        self.assertEqual(self.calls[1][1], ["One here."])

    def test_marks_with_no_tail_fire_before_on_done(self):
        order = []
        import threading
        done = threading.Event()
        sp2 = speech.SentenceSpeaker(
            {"voice": {"enabled": "true", "cmd": self.script}},
            on_sentence=lambda pts: order.append(("pts", pts)))
        sp2.finish("", on_done=lambda: (order.append("done"), done.set()),
                   marks=[(0, "p1")])
        self.assertTrue(done.wait(timeout=10))
        self.assertEqual(order, [("pts", ["p1"]), "done"])

    def test_late_mark_for_dequeued_sentence_fires_at_once(self):
        sp = self.speaker()
        sp.feed("One here. ", [])
        self.assertTrue(self.wait_for(lambda: self.spoken_now()))
        sp.feed("One here. ", [(9, "late")])
        self.assertEqual([c[0] for c in self.calls], [["late"]])
        self.finish(sp, "One here.")

    def test_late_mark_for_queued_sentence_rides_with_it(self):
        # first sentence occupies the worker; second is still queued. The
        # fake TTS blocks on a gate file, so sentence 1 cannot finish (and
        # sentence 2 cannot be dequeued) until the test releases it.
        gate = pathlib.Path(self.dir.name) / "gate"
        gated = pathlib.Path(self.dir.name) / "gated.sh"
        gated.write_text(f'#!/bin/sh\necho "$(cat)" >> {self.log}\n'
                         f'while [ ! -e {gate} ]; do sleep 0.02; done\n')
        gated.chmod(gated.stat().st_mode | stat.S_IXUSR)
        sp = self.speaker(cmd=str(gated))
        sp.feed("One here. Two there. ", [])
        self.assertTrue(self.wait_for(self.spoken_now))
        sp.feed("One here. Two there. ", [(19, "rides")])
        self.assertEqual(self.calls, [])
        gate.touch()
        self.finish(sp, "One here. Two there.", [(19, "rides")])
        self.assertEqual([c[0] for c in self.calls], [["rides"]])
        self.assertEqual(self.calls[0][1], ["One here."])

    def test_every_mark_fires_exactly_once(self):
        sp = self.speaker()
        marks = [(8, "a"), (19, "b"), (26, "c")]
        sp.feed("One here. Two there. ", marks[:2])
        sp.feed("One here. Two there. Three ", marks[:2])
        self.finish(sp, "One here. Two there. Three x", marks)
        fired = [p for c in self.calls for p in c[0]]
        self.assertEqual(sorted(fired), ["a", "b", "c"])

    def test_stop_drops_queued_points(self):
        stopper = speech.SentenceSpeaker(
            {"voice": {"enabled": "true", "cmd": self.script}},
            on_sentence=lambda pts: (self.calls.append((pts, None)),
                                     stopper.stop()))
        stopper.feed("One here. Two there. ", [(8, "p1"), (19, "p2")])
        self.assertTrue(self.wait_for(lambda: self.calls))
        time.sleep(0.5)
        self.assertEqual([c[0] for c in self.calls], [["p1"]])

    def test_voice_disabled_never_calls_back(self):
        sp = speech.SentenceSpeaker({"voice": {"enabled": "false"}},
                                    on_sentence=self.on_sentence)
        sp.feed(self.TEXT + " ", [(8, "p1")])
        sp.finish(self.TEXT, marks=[(19, "p2")])
        self.assertEqual(self.calls, [])

SECRET = "zebra-quartz-7731 private sentence"


class PrivateTextTests(unittest.TestCase):
    """The reply text never appears in a TTS child's command line: other
    local accounts can read argv while the child runs, so the text goes
    to stdin."""

    def setUp(self):
        speech.stop()
        self.dir = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.dir.name)
        self.cmdlines, self.stdins = d / "cmdlines", d / "stdins"
        script = d / "tts.sh"
        script.write_text(
            "#!/bin/sh\n"
            f'tr "\\0" " " < /proc/$$/cmdline >> {self.cmdlines}\n'
            f'echo >> {self.cmdlines}\n'
            f'cat >> {self.stdins}\n'
            f'echo >> {self.stdins}\n')
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        self.script = str(script)

    def tearDown(self):
        speech.stop()
        self.dir.cleanup()

    def wait(self, path, n):
        for _ in range(100):
            if path.exists() and path.read_text().count("\n") >= n:
                return path.read_text()
            time.sleep(0.05)
        self.fail(f"{path.name} never got {n} lines")

    def check(self, *needles):
        argv = self.wait(self.cmdlines, 1)
        said = self.wait(self.stdins, 1)
        self.assertNotIn("zebra-quartz", argv)
        for n in needles:
            self.assertIn(n, said)

    def test_a_complete_reply_goes_to_stdin_not_argv(self):
        cfg = {"voice": {"enabled": "true", "cmd": self.script}}
        proc = speech.speak(SECRET, cfg)
        proc.wait(timeout=5)
        self.check(SECRET)

    def test_a_text_placeholder_is_not_put_on_argv(self):
        cfg = {"voice": {"enabled": "true",
                         "cmd": f"{self.script} {{text}}"}}
        proc = speech.speak(SECRET, cfg)
        proc.wait(timeout=5)
        self.check(SECRET)

    def test_streamed_sentences_go_to_stdin_not_argv(self):
        cfg = {"voice": {"enabled": "true", "cmd": self.script}}
        sp = speech.SentenceSpeaker(cfg)
        sp.feed("zebra-quartz-7731 one. zebra-quartz-7731 two. ")
        sp.finish("zebra-quartz-7731 one. zebra-quartz-7731 two.")
        sp._worker.join(timeout=5)
        self.wait(self.stdins, 2)
        self.assertNotIn("zebra-quartz", self.wait(self.cmdlines, 2))
        self.assertEqual(self.stdins.read_text().count("zebra-quartz"), 2)

    def test_the_builtin_engine_reads_stdin(self):
        with mock.patch.object(platform, "tts_binary",
                               return_value="espeak-ng"):
            argv = speech._argv({"voice": {"enabled": "true"}})
        self.assertEqual(argv, ["espeak-ng", "--stdin"])


if __name__ == "__main__":
    unittest.main()
