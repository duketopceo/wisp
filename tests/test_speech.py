import pathlib
import stat
import tempfile
import time
import unittest

from wisp import speech


def _proc():
    return speech._PROC


class SpeechTests(unittest.TestCase):
    def setUp(self):
        speech.stop()
        self.dir = tempfile.TemporaryDirectory()
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
        script = pathlib.Path(self.dir.name) / "echo.sh"
        out = pathlib.Path(self.dir.name) / "out.txt"
        script.write_text(f'#!/bin/sh\necho "$1" > {out}\n')
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        speech.speak("hello world", self.cfg(f"{script} {{text}}"))
        for _ in range(50):
            if out.exists():
                break
            time.sleep(0.05)
        self.assertEqual(out.read_text().strip(), "hello world")

    def test_on_exit_fires_and_clears(self):
        import threading
        done = threading.Event()
        script = pathlib.Path(self.dir.name) / "fast.sh"
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        proc = speech.speak("hi", self.cfg(str(script)))
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


if __name__ == "__main__":
    unittest.main()
