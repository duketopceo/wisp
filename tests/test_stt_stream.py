"""Streaming STT while the key is held: chunking, joining, fallbacks."""
import array
import math
import pathlib
import struct
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import config, dictate_history, stage_capture, stt_stream as S  # noqa: E402


def tone(seconds, amp=8000):
    n = int(S.RATE * seconds)
    a = array.array("h", (int(amp * math.sin(i * 0.3)) for i in range(n)))
    return a.tobytes()


def quiet(seconds):
    return b"\x00\x00" * int(S.RATE * seconds)


def write_wav(path, pcm):
    path.write_bytes(S.wav_bytes(pcm))


class FakeFn:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, path):
        data = pathlib.Path(path).read_bytes()
        self.calls.append(len(data) - 44)
        if self.fail_on == len(self.calls):
            raise RuntimeError("stt down")
        return f"part{len(self.calls)}"


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.path = pathlib.Path(td.name) / "u.wav"

    def stream(self, pcm, fn, wait_texts=1):
        write_wav(self.path, pcm)
        s = S.Streamer(self.path, transcribe_fn=fn, tick_s=0.01).start()
        for _ in range(300):
            if len(s.texts) >= wait_texts or s.failed:
                break
            time.sleep(0.02)
        return s


class HeaderTests(Base):
    def test_canonical_header_offset(self):
        self.assertEqual(S.data_offset(S.wav_bytes(b"\0\0" * 10)[:4096]), 44)

    def test_other_formats_are_refused(self):
        bad = bytearray(S.wav_bytes(b"\0\0" * 10))
        struct.pack_into("<I", bad, 24, 44100)   # sample rate
        self.assertIsNone(S.data_offset(bytes(bad)))
        self.assertIsNone(S.data_offset(b"not a wav" * 10))

    def test_list_chunk_before_data_is_skipped(self):
        raw = S.wav_bytes(b"\0\0" * 10)
        head = raw[:36] + b"LIST" + struct.pack("<I", 4) + b"INFO" + raw[36:]
        self.assertEqual(S.data_offset(head), 56)


class CutTests(unittest.TestCase):
    def test_cut_lands_in_the_quiet_gap(self):
        pcm = tone(6.4) + quiet(0.4) + tone(3.0)
        at = S.quiet_cut(pcm, 5.0, 7.5)
        self.assertGreaterEqual(at, int(6.4 * S.BPS))
        self.assertLessEqual(at, int(6.8 * S.BPS))
        self.assertEqual(at % 2, 0)


class StreamerTests(Base):
    def test_long_utterance_cuts_a_chunk_and_transcribes_the_rest(self):
        fn = FakeFn()
        s = self.stream(tone(6.3) + quiet(0.5) + tone(6.4) + quiet(0.5)
                        + tone(3.0), fn, wait_texts=2)
        self.assertGreaterEqual(len(s.texts), 2)
        n = len(s.texts)
        text = s.finish()
        self.assertEqual(text.split()[:n], [f"part{i + 1}" for i in range(n)])
        self.assertEqual(len(text.split()), n + 1)   # plus the remainder
        self.assertEqual(sum(fn.calls[:-1]), s.cut)  # chunks tile the audio

    def test_short_utterance_never_streams(self):
        fn = FakeFn()
        s = self.stream(tone(3.0), fn)
        time.sleep(0.2)
        self.assertIsNone(s.finish())
        self.assertEqual(fn.calls, [])

    def test_silent_chunk_is_not_sent(self):
        fn = FakeFn()
        s = self.stream(quiet(9.0) + tone(2.0), fn)
        text = s.finish()
        self.assertEqual(s.texts, [""])
        self.assertEqual(len(fn.calls), 1)   # only the spoken remainder
        self.assertEqual(text, "part1")

    def test_chunk_failure_falls_back_to_the_whole_file(self):
        s = self.stream(tone(9.0), FakeFn(fail_on=1))
        self.assertTrue(s.failed)
        self.assertIsNone(s.finish())

    def test_tiny_tail_is_dropped_not_sent(self):
        fn = FakeFn()
        pcm = tone(6.3) + quiet(0.5) + tone(1.7)
        s = self.stream(pcm, fn)
        s._stop.set()
        s._thread.join()
        fn.calls.clear()
        s.cut = len(pcm) - int(0.1 * S.BPS)
        s.texts = ["a"]
        self.assertEqual(s.finish(), "a")
        self.assertEqual(fn.calls, [])


class RegistryTests(Base):
    def test_begin_replaces_the_previous_unclaimed_watch(self):
        proc = mock.Mock()
        proc.poll.return_value = 0
        a = S.begin(self.path, proc)
        other = self.path.with_name("v.wav")
        b = S.begin(other, proc)
        self.assertIsNone(S.claim(self.path))
        self.assertIs(S.claim(other), b)
        self.assertIsNone(S.claim(other))
        self.assertIsNotNone(a)


class TranscribeSeamTests(Base):
    CFG = {"stt": {"provider": "openai"}}

    def test_streamed_text_skips_the_whole_file_request(self):
        fake = mock.Mock(finish=mock.Mock(return_value="open my email"))
        with mock.patch.object(S, "claim", return_value=fake), \
                mock.patch.object(stage_capture, "_transcribe_openai") as t:
            self.assertEqual(stage_capture.transcribe(self.path, self.CFG),
                             "open my email")
        t.assert_not_called()

    def test_fallback_when_the_stream_gives_up(self):
        fake = mock.Mock(finish=mock.Mock(return_value=None))
        with mock.patch.object(S, "claim", return_value=fake), \
                mock.patch.object(stage_capture, "_transcribe_openai",
                                  return_value="whole file") as t:
            self.assertEqual(stage_capture.transcribe(self.path, self.CFG),
                             "whole file")
        t.assert_called_once()

    def test_no_stream_is_the_ordinary_path(self):
        with mock.patch.object(S, "claim", return_value=None), \
                mock.patch.object(stage_capture, "_transcribe_openai",
                                  return_value="plain") as t:
            self.assertEqual(stage_capture.transcribe(self.path, self.CFG),
                             "plain")
        t.assert_called_once()

    def test_streaming_can_be_turned_off(self):
        s = S.Streamer(self.path, tick_s=0.01)
        write_wav(self.path, tone(9.0))
        cfg = {"stt": {"provider": "openai", "streaming": "false"}}
        with mock.patch("wisp.config.load_config", return_value=cfg):
            self.assertIsNone(s._setup())


class AbortDeterministicTests(unittest.TestCase):
    """Cancellation timing without starting a thread or opening a WAV."""
    def stream(self):
        stop = mock.Mock()
        stop.is_set.return_value = False
        stop.set.side_effect = lambda: setattr(stop.is_set, "return_value", True)
        with mock.patch.object(S.threading, "Event", return_value=stop):
            s = S.Streamer("/fake/capture.wav",
                           transcribe_fn=mock.Mock())
        s.path = mock.MagicMock(spec=pathlib.Path)
        s.path.open.return_value.__enter__.return_value.read.return_value = b""
        s._thread = mock.Mock()
        s._setup = mock.Mock(return_value=44)
        s._transcribe = mock.Mock(return_value="must not be sent")
        return s

    def test_cancel_during_sleep_never_reads_or_submits_next_chunk(self):
        s = self.stream()
        with mock.patch.object(S.time, "sleep", side_effect=lambda _: s.abort()):
            s._run()
        s.path.open.assert_not_called()
        s._transcribe.assert_not_called()
        s._thread.join.assert_called_once_with(timeout=S.ABORT_JOIN_S)

    def test_cancel_during_read_never_submits_the_chunk(self):
        s = self.stream()
        reader = s.path.open.return_value.__enter__.return_value
        reader.read.side_effect = lambda _: (
            s.abort(), b"\0" * int((s.chunk_s + S.SEARCH_S) * S.BPS))[1]
        with mock.patch.object(S.time, "sleep"), \
             mock.patch.object(S, "quiet_cut", return_value=100):
            s._run()
        s._transcribe.assert_not_called()
        self.assertEqual(s.texts, [])

    def test_failed_start_discards_partial_watch_preserving_error(self):
        s = self.stream()
        failure = OSError("stream thread startup failed")
        s.start = mock.Mock(side_effect=failure)
        s._thread.join.side_effect = RuntimeError("partial thread")
        streams = {}
        with mock.patch.object(S, "Streamer", return_value=s), \
             mock.patch.object(S, "_STREAMS", streams), \
             mock.patch.object(config, "load_config", return_value={}), \
             mock.patch.object(dictate_history, "Journal"):
            with self.assertRaises(OSError) as caught:
                S.begin("/fake/capture.wav", mock.Mock())
        self.assertIs(caught.exception, failure)
        self.assertEqual(streams, {})
        s._stop.set.assert_called_once_with()
        s._thread.join.assert_called_once_with(timeout=S.ABORT_JOIN_S)
        s._transcribe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
