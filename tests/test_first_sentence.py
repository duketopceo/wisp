"""B2: the first words are spoken sooner.

Unit tests for where the speaker cuts, and an A/B through the replay
harness: the same streamed reply with `[voice] early_clause` off and on,
measured from the brain request to the first TTS spawn. Fakes only, so the
gain is the streaming wait the change removes; live numbers are pending.
"""
import copy
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from wisp import speech  # noqa: E402
from harness import runner  # noqa: E402

LONG = ("Sure, here is the short version of that answer, which keeps going "
        "for a while before it ends. Then a second sentence.")


class Capture:
    """Records what the speaker would say, without spawning anything."""

    def __init__(self, cfg=None):
        self.said = []
        base = {"voice": {"enabled": "true", "cmd": "x"}}
        for k, v in (cfg or {}).items():
            base["voice"][k] = v
        self.cfg = base

    def speaker(self):
        sp = speech.SentenceSpeaker(self.cfg)
        self._patch = mock.patch.object(
            speech, "_argv", side_effect=lambda m, c, lang="": self.said.append(m))
        self._patch.start()
        return sp


def say_all(text, stream=0, **cfg):
    """What gets spoken for `text`; `stream` > 0 feeds it that many
    characters at a time first, as a streaming model would."""
    cap = Capture(cfg)
    sp = cap.speaker()
    for i in range(stream, len(text), stream or len(text) + 1):
        sp.feed(text[:i])
    sp.finish(text)
    sp._worker.join(timeout=5)
    cap._patch.stop()
    return cap.said


class Splitting(unittest.TestCase):
    def test_a_long_first_sentence_is_cut_at_its_first_clause(self):
        said = say_all(LONG, stream=7)
        self.assertEqual(said[0], "Sure, here is the short version of "
                                  "that answer,")
        self.assertEqual(" ".join(said), LONG)

    def test_only_the_first_chunk_is_cut_at_a_clause(self):
        said = say_all("Short one. And a second sentence, with a comma that "
                       "is well past twenty-eight characters, so it stays "
                       "whole. Done.")
        self.assertEqual(said[1], "And a second sentence, with a comma that "
                                  "is well past twenty-eight characters, "
                                  "so it stays whole.")

    def test_a_short_clause_is_not_worth_a_start(self):
        said = say_all("Yes, it is. Next.")
        self.assertEqual(said, ["Yes, it is.", "Next."])

    def test_a_finished_sentence_is_spoken_whole(self):
        said = say_all(LONG)
        self.assertEqual(said[0], "Sure, here is the short version of that "
                                  "answer, which keeps going for a while "
                                  "before it ends.")

    def test_off_waits_for_the_full_stop(self):
        said = say_all(LONG, stream=7, early_clause="false")
        self.assertEqual(said[0], "Sure, here is the short version of that "
                                  "answer, which keeps going for a while "
                                  "before it ends.")

    def test_an_ellipsis_ends_a_sentence(self):
        said = say_all("Let me think\u2026 It is half past three.")
        self.assertEqual(said, ["Let me think\u2026",
                                "It is half past three."])

    def test_decimals_and_abbreviation_free_text_are_not_split(self):
        said = say_all("It is 3.5 percent higher than last year, which "
                       "is a lot.")
        self.assertEqual(" ".join(said),
                         "It is 3.5 percent higher than last year, which "
                         "is a lot.")
        self.assertNotIn("3.", said)


def streamed_fixture(early: bool, log: str) -> dict:
    fx = copy.deepcopy(runner.load_fixture("ask"))
    fx["endpoints"]["whisper"]["transcript"] = "explain it"
    fx["endpoints"]["brain"]["responses"] = [{
        "chunks": ["Sure, here is the short version of that answer, ",
                   "which keeps going for a while ",
                   "before it finally ends. ",
                   "Then a second sentence."],
        "chunk_delay_ms": 200}]
    probe = ("import time,sys; open(sys.argv[1],'a').write("
             "repr(time.monotonic())+chr(10))")
    fx["config"] = {"voice": {
        "enabled": "true",
        "early_clause": "true" if early else "false",
        "cmd": f"{sys.executable} -c \"{probe}\" {log} {{text}}"}}
    fx["expect"] = {}
    return fx


def first_audio_ms(early: bool) -> float:
    with tempfile.TemporaryDirectory() as td:
        log = str(pathlib.Path(td) / "tts.log")
        res = runner.run_turn(streamed_fixture(early, log))
        calls = res.calls.get("brain") or res.calls.get("brain_chat") or []
        t0 = min(c["t"] for c in calls)
        stamps = [float(x) for x in
                  pathlib.Path(log).read_text().split()]
    return (min(stamps) - t0) * 1000


class ReplayBeforeAfter(unittest.TestCase):
    def test_first_audio_is_at_least_300ms_earlier(self):
        before = first_audio_ms(False)
        after = first_audio_ms(True)
        self.assertGreaterEqual(before - after, 300,
                                f"before {before:.0f} ms, after "
                                f"{after:.0f} ms")


if __name__ == "__main__":
    unittest.main()
