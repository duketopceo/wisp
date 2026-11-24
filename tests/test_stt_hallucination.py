#!/usr/bin/env python3
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import stage_capture, stt_audio, stt_hallucination, turn_router  # noqa: E402


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

    def test_strips_thanks_for_watching_not_bare_thanks(self):
        text = "Let's test it out and see what we can do The End"
        quiet = {"tail_quiet": True, "tail_rms": 8, "tail_s": 2.0}
        out, meta = stt_hallucination.strip_trailing_hallucination(text, quiet)
        self.assertEqual(out, "Let's test it out and see what we can do")
        self.assertTrue(meta.get("stripped"))

    def test_keeps_thank_you_on_quiet_tail(self):
        text = "That worked thank you"
        quiet = {"tail_quiet": True, "tail_rms": 5, "tail_s": 1.0}
        out, meta = stt_hallucination.strip_trailing_hallucination(text, quiet)
        self.assertEqual(text, out)
        self.assertEqual(meta, {})

    def test_only_hallucination_on_quiet_tail_returns_empty(self):
        text = "The End"
        quiet = {"tail_quiet": True, "tail_rms": 3, "tail_s": 2.0}
        out, meta = stt_hallucination.strip_trailing_hallucination(text, quiet)
        self.assertEqual(out, "")
        self.assertEqual(meta.get("reason"), "quiet_tail_only")

    def test_low_tail_energy_requires_tail_quiet_key(self):
        self.assertFalse(stt_hallucination.low_tail_energy({"tail_rms": 1}))
        self.assertFalse(stt_hallucination.low_tail_energy(None))
        self.assertTrue(
            stt_hallucination.low_tail_energy({"tail_quiet": True, "tail_rms": 1})
        )


class SttAudioTrimTests(unittest.TestCase):
    def _wav(self, pcm: bytes) -> pathlib.Path:
        from wisp import stt_stream
        fd, path = tempfile.mkstemp(suffix=".wav")
        with open(fd, "wb") as f:
            f.write(stt_stream.wav_bytes(pcm))
        return pathlib.Path(path)

    def test_trim_drops_trailing_silence(self):
        from wisp import stt_stream
        rate = stt_stream.RATE
        loud = b"\x80\x00" * int(rate * 0.8)
        silence = b"\x00\x00" * int(rate * 2.0)
        pcm = loud + silence
        path = self._wav(pcm)
        out, meta, _tmp = stt_audio.prepare_for_stt(path)
        try:
            self.assertTrue(meta.get("trimmed"))
            out_pcm, _ = stt_audio._read_pcm(out)
            self.assertLess(len(out_pcm), len(pcm))
        finally:
            path.unlink(missing_ok=True)
            if out != path:
                out.unlink(missing_ok=True)

    def test_no_trim_when_no_speech_frame_detected(self):
        from wisp import stt_stream
        rate = stt_stream.RATE
        quiet = b"\x08\x00" * int(rate * 1.0)
        path = self._wav(quiet)
        try:
            out, meta, tmp = stt_audio.prepare_for_stt(path)
            self.assertEqual(out, path)
            self.assertFalse(meta.get("trimmed"))
            self.assertTrue(meta.get("no_speech_detected"))
            self.assertIsNone(tmp)
        finally:
            path.unlink(missing_ok=True)

    def test_wrong_rate_raises(self):
        import wave
        from wisp import stt_stream
        path = self._wav(b"\x00\x00" * 100)
        with wave.open(str(path), "rb") as w:
            frames = w.readframes(w.getnframes())
        bad = path.with_suffix(".bad.wav")
        with wave.open(str(bad), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(frames)
        try:
            with self.assertRaises(wave.Error):
                stt_audio._read_pcm(bad)
        finally:
            path.unlink(missing_ok=True)
            bad.unlink(missing_ok=True)


class TranscribeStreamAbortTests(unittest.TestCase):
    def test_abort_stream_when_trim_replaces_wav(self):
        wav = pathlib.Path("/tmp/orig.wav")
        trimmed = pathlib.Path("/tmp/trim.wav")
        stream = mock.Mock()
        with mock.patch.object(stage_capture, "_stt_tail_trim", return_value=True), \
             mock.patch("wisp.stt_audio.prepare_for_stt",
                        return_value=(trimmed, {"tail_quiet": False}, trimmed)), \
             mock.patch("wisp.stt_stream.claim", return_value=stream) as claim, \
             mock.patch("wisp.warm.claim"), \
             mock.patch.object(
                 stage_capture, "_transcribe_openai", return_value="ok"), \
             mock.patch.object(
                 stage_capture, "_postprocess_transcript",
                 return_value=("ok", {})):
            cfg = {"stt": {"provider": "openai", "model": "x",
                           "base_url": "https://example", "key_env": "K"}}
            with mock.patch("wisp.config.stt_settings", return_value=cfg["stt"]):
                out = stage_capture.transcribe(wav, cfg)
        self.assertEqual(out, "ok")
        claim.assert_called_once_with(wav)
        stream.abort.assert_called_once()
        stream.finish.assert_not_called()


class RouteDeadlineTests(unittest.TestCase):
    def test_ask_model_caps_entire_chat_under_deadline(self):
        def slow_chat(msgs, cfg, timeout=None, **kw):
            self.assertLessEqual(timeout, 0.05)
            import time
            time.sleep(0.2)
            return {"content": "linux"}

        out = turn_router.ask_model("hi", {}, "test", 0.05, chat=slow_chat)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()