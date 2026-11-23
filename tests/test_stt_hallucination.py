#!/usr/bin/env python3
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import stt_audio, stt_hallucination  # noqa: E402


class SttHallucinationTests(unittest.TestCase):
    def test_keeps_real_the_end_when_tail_is_loud(self):
        text = "We watched The End of the affair"
        quiet = {"tail_quiet": False, "tail_rms": 200}
        out, meta = stt_hallucination.strip_trailing_hallucination(text, quiet)
        self.assertEqual(text, out)
        self.assertEqual(meta, {})

    def test_strips_whisper_outro_on_quiet_tail(self):
        text = "What time is it in Tokyo? The End"
        quiet = {"tail_quiet": True, "tail_rms": 12, "tail_s": 1.2}
        out, meta = stt_hallucination.strip_trailing_hallucination(text, quiet)
        self.assertEqual(out, "What time is it in Tokyo?")
        self.assertIn("stripped", meta)

    def test_strips_thanks_for_watching(self):
        text = "Let's test it out and see what we can do The End"
        quiet = {"tail_quiet": True, "tail_rms": 8, "tail_s": 2.0}
        out, meta = stt_hallucination.strip_trailing_hallucination(text, quiet)
        self.assertEqual(out, "Let's test it out and see what we can do")
        self.assertTrue(meta.get("stripped"))


class SttAudioTrimTests(unittest.TestCase):
    def test_trim_drops_trailing_silence(self):
        import wave
        from wisp import stt_stream
        rate = stt_stream.RATE
        speech = b"\x20\x00" * int(rate * 0.8)
        silence = b"\x00\x00" * int(rate * 2.0)
        pcm = speech + silence
        fd, path = tempfile.mkstemp(suffix=".wav")
        with open(fd, "wb") as f:
            f.write(stt_stream.wav_bytes(pcm))
        out, meta, _tmp = stt_audio.prepare_for_stt(pathlib.Path(path))
        try:
            self.assertTrue(meta.get("trimmed"))
            out_pcm, _ = stt_audio._read_pcm(out)
            self.assertLess(len(out_pcm), len(pcm))
        finally:
            pathlib.Path(path).unlink(missing_ok=True)
            if out != pathlib.Path(path):
                out.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()