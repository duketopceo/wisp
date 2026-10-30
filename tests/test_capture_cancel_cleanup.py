"""Daemon discard paths use the capture owner's cleanup, never audio or I/O."""
import importlib.machinery
import importlib.util
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import config, handsfree, ipc, pipeline, stage_capture, stt_stream
from wisp import trace, voice_polish


class CaptureDiscardTests(unittest.TestCase):
    def setUp(self):
        path = str(pathlib.Path(__file__).resolve().parent.parent / "wispd")
        loader = importlib.machinery.SourceFileLoader("wispd_u14_cleanup", path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.w = importlib.util.module_from_spec(spec)
        loader.exec_module(self.w)
        self.proc = mock.Mock()
        self.proc.poll.return_value = None
        self.out = mock.Mock(spec=pathlib.Path)
        self.out.exists.side_effect = AssertionError("discard must not read audio")
        self.sampler = mock.Mock()
        self.stop = mock.Mock()
        self.rec = {"proc": self.proc, "out": self.out, "t0": 10.0,
                    "sampler_stop": self.stop, "sampler": self.sampler,
                    "ducked_vol": 0.8}
        self.st = mock.Mock()
        self.speculation = mock.Mock()
        self.ctl = {"rec": self.rec, "rec_lock": mock.MagicMock(),
                    "turn": "t14", "spec": self.speculation,
                    "busy": mock.Mock(), "interrupt": mock.Mock()}
        self.ctl["busy"].is_set.return_value = False
        self.patch(self.w, "dlog")
        self.patch(self.w, "_tap_chips", return_value={})
        self.patch(self.w, "_interrupt")
        self.patch(self.w.time, "monotonic", return_value=10.1)
        self.patch(ipc, "check_peer_authz", return_value=None)
        self.patch(handsfree, "intercept", return_value=None)
        self.patch(handsfree, "interrupted")
        self.patch(trace, "emit")
        self.patch(self.w.state_mod, "action_add")
        self.patch(self.w.speech, "stop")
        self.patch(pipeline.subprocess, "Popen",
                   side_effect=AssertionError("real process forbidden"))
        self.patch(pipeline.subprocess, "run",
                   side_effect=AssertionError("real command forbidden"))
        self.patch(self.w.threading, "Thread",
                   side_effect=AssertionError("real thread forbidden"))
        self.patch(config, "LEVEL_FILE", mock.Mock(spec=pathlib.Path))
        self.restore = self.patch(voice_polish, "restore_speaker")
        self.handle = self.w._handler(self.st, {}, self.ctl)

    def patch(self, obj, name, *args, **kwargs):
        p = mock.patch.object(obj, name, *args, **kwargs)
        value = p.start()
        self.addCleanup(p.stop)
        return value

    def assert_audio_released(self):
        self.assertIsNone(self.ctl["rec"])
        self.restore.assert_called_once_with(0.8)
        self.assertNotIn("ducked_vol", self.rec)
        self.stop.set.assert_called_once_with()
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.proc.wait.assert_called_once_with(timeout=3)
        self.speculation.cancel.assert_called_once_with()

    def registered_stream(self):
        stop = mock.Mock()
        with mock.patch.object(stt_stream.threading, "Event", return_value=stop):
            stream = stt_stream.Streamer(
                "/fake/capture.wav", proc=self.proc,
                transcribe_fn=mock.Mock(
                    side_effect=AssertionError("discard must not transcribe")))
        stream._thread = mock.Mock()
        streams = {str(self.out): stream}
        self.patch(stt_stream, "_STREAMS", streams)
        return stream, stop, streams

    def test_phantom_release_restores_owned_capture(self):
        result = self.handle({"cmd": "listen", "phase": "stop"})
        self.assertTrue(result["ignored"])
        self.assert_audio_released()
        self.st.turn.return_value.set_level.assert_called_once_with(0.0)
        self.st.turn.return_value.transition.assert_called_once_with(
            "done", result="", transcript="")

    def test_interrupt_restores_owned_capture_before_settling_idle(self):
        self.assertEqual(self.handle({"cmd": "interrupt"}), {"ok": True})
        self.assert_audio_released()
        self.st.turn.return_value.set_level.assert_called_once_with(0.0)
        self.st.turn.return_value.transition.assert_called_once_with(
            "idle", error="", error_code="cancelled", error_detail="",
            choices=[], prompt_id="", confirm=None, result="", transcript="")

    def test_phantom_release_discards_stream_without_transcribing(self):
        stream, stop, streams = self.registered_stream()
        self.assertTrue(self.handle({"cmd": "listen", "phase": "stop"})["ignored"])
        self.assertEqual(streams, {})
        stop.set.assert_called_once_with()
        stream._thread.join.assert_called_once_with(
            timeout=stt_stream.ABORT_JOIN_S)
        stream._fn.assert_not_called()
        self.assert_audio_released()

    def test_interrupt_wait_failure_discards_stream_preserves_primary(self):
        stream, stop, streams = self.registered_stream()
        failure = OSError("original recorder wait failed")
        self.proc.wait.side_effect = [failure, None]
        with self.assertRaises(OSError) as caught:
            self.handle({"cmd": "interrupt"})
        self.assertIs(caught.exception, failure)
        self.assertEqual(streams, {})
        stop.set.assert_called_once_with()
        stream._thread.join.assert_called_once_with(
            timeout=stt_stream.ABORT_JOIN_S)
        stream._fn.assert_not_called()
        self.restore.assert_called_once_with(0.8)
        self.proc.kill.assert_called_once_with()

    def test_empty_audio_discards_unclaimable_stream(self):
        stream, stop, streams = self.registered_stream()
        self.out.exists.side_effect = None
        self.out.exists.return_value = False
        with self.assertRaisesRegex(RuntimeError, "produced no audio"):
            pipeline.record_stop(self.rec, self.st.turn("t14"))
        self.assertEqual(streams, {})
        stop.set.assert_called_once_with()
        stream._fn.assert_not_called()
        self.restore.assert_called_once_with(0.8)

    def test_interrupt_failure_still_cancels_speculation(self):
        failure = OSError("original wait error")
        self.proc.wait.side_effect = [failure, None]
        self.speculation.cancel.side_effect = RuntimeError("spec cleanup failed")
        with self.assertRaises(OSError) as caught:
            self.handle({"cmd": "interrupt"})
        self.assertIs(caught.exception, failure)
        self.speculation.cancel.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)

    def test_phantom_failure_still_cancels_speculation(self):
        failure = OSError("original phantom wait error")
        self.proc.wait.side_effect = [failure, None]
        self.speculation.cancel.side_effect = RuntimeError("spec cleanup failed")
        with self.assertRaises(OSError) as caught:
            self.handle({"cmd": "listen", "phase": "stop"})
        self.assertIs(caught.exception, failure)
        self.speculation.cancel.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)

    def test_interrupt_discards_stream_once_even_on_duplicate_cleanup(self):
        stream, stop, streams = self.registered_stream()
        self.assertEqual(self.handle({"cmd": "interrupt"}), {"ok": True})
        self.assertEqual(self.handle({"cmd": "interrupt"}), {"ok": True})
        pipeline.record_stop(self.rec, self.st.turn("t14"), discard=True)
        self.assertEqual(streams, {})
        stop.set.assert_called_once_with()
        stream._thread.join.assert_called_once_with(
            timeout=stt_stream.ABORT_JOIN_S)
        stream._fn.assert_not_called()
        self.assert_audio_released()

    def test_phantom_mini_discards_audio_without_settling_parked_turn(self):
        stream, stop, streams = self.registered_stream()
        self.ctl["mini"] = "choice"
        result = self.handle({"cmd": "listen", "phase": "stop"})
        self.assertTrue(result["ignored"])
        self.assertEqual(streams, {})
        stop.set.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.st.turn.assert_not_called()
        self.speculation.cancel.assert_not_called()
        config.LEVEL_FILE.write_text.assert_called_once_with("0.0")
        stream._fn.assert_not_called()

    def test_interrupt_does_not_take_running_turns_mini_capture(self):
        self.ctl["mini"] = "choice"
        self.assertFalse(self.w._cancel_recording(self.st, self.ctl))
        self.assertIs(self.ctl["rec"], self.rec)
        self.proc.send_signal.assert_not_called()
        self.restore.assert_not_called()

    def test_discard_timeout_kills_and_reaps_before_restoring(self):
        stream, stop, streams = self.registered_stream()
        self.proc.wait.side_effect = [
            subprocess.TimeoutExpired("fake recorder", 3), None]
        self.assertTrue(self.handle({"cmd": "listen", "phase": "stop"})["ignored"])
        self.assertEqual(streams, {})
        self.proc.kill.assert_called_once_with()
        self.assertEqual(self.proc.wait.call_args_list,
                         [mock.call(timeout=3), mock.call(timeout=3)])
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        stop.set.assert_called_once_with()
        stream._fn.assert_not_called()

    def test_normal_stop_keeps_stream_for_transcribe_to_claim(self):
        stream, stop, streams = self.registered_stream()
        stream._thread.is_alive.return_value = False
        stream.texts = ["saved transcript"]
        stream.path = mock.Mock(spec=pathlib.Path)
        stream.path.read_bytes.return_value = stt_stream.wav_bytes(b"")
        self.out.exists.side_effect = None
        self.out.exists.return_value = True
        self.out.stat.return_value.st_size = 80
        self.assertIs(pipeline.record_stop(self.rec, self.st.turn("t14")), self.out)
        self.assertIs(streams[str(self.out)], stream)
        stop.set.assert_not_called()
        stream._thread.join.assert_not_called()
        with mock.patch.object(stage_capture, "_transcribe_openai",
                               side_effect=AssertionError("network forbidden")):
            text = pipeline.transcribe(self.out, {"stt": {"provider": "openai"}})
        self.assertEqual(text, "saved transcript")
        self.assertEqual(streams, {})
        stop.set.assert_called_once_with()
        stream._thread.join.assert_called_once_with(timeout=stt_stream.JOIN_S)
        stream._fn.assert_not_called()

    def test_wav_validation_error_discards_stream_without_hiding_error(self):
        stream, stop, streams = self.registered_stream()
        self.out.exists.side_effect = None
        self.out.exists.return_value = True
        failure = OSError("audio stat failed")
        self.out.stat.side_effect = failure
        with self.assertRaises(OSError) as caught:
            pipeline.record_stop(self.rec, self.st.turn("t14"))
        self.assertIs(caught.exception, failure)
        self.assertEqual(streams, {})
        stop.set.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)
        stream._fn.assert_not_called()

    def test_failed_stop_and_stream_join_do_not_replace_primary_error(self):
        stream, stop, streams = self.registered_stream()
        failure = KeyboardInterrupt("cancel while stopping recorder")
        self.proc.wait.side_effect = [failure, OSError("reap failure")]
        self.proc.kill.side_effect = OSError("kill failure")
        stop.set.side_effect = RuntimeError("stream stop failure")
        stream._thread.join.side_effect = RuntimeError("stream join failure")
        self.sampler.join.side_effect = RuntimeError("sampler join failure")
        self.restore.side_effect = OSError("restore failure")
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.handle({"cmd": "interrupt"})
        self.assertIs(caught.exception, failure)
        self.assertEqual(streams, {})
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        stream._thread.join.assert_called_once_with(
            timeout=stt_stream.ABORT_JOIN_S)
        self.restore.assert_called_once_with(0.8)
        self.speculation.cancel.assert_called_once_with()
        stream._fn.assert_not_called()

    def test_busy_watchdog_discards_instead_of_leaving_an_unclaimed_stream(self):
        stream, stop, streams = self.registered_stream()
        self.out.exists.side_effect = None
        self.out.exists.return_value = True
        self.out.stat.return_value.st_size = 80
        self.ctl["stop"] = mock.Mock()
        self.ctl["busy"].is_set.return_value = True
        self.patch(self.w, "_DAEMON_CTL", self.ctl)
        self.patch(self.w, "_DAEMON_ST", self.st)
        self.w._rec_watchdog(self.ctl, 60)
        self.assertEqual(streams, {})
        self.assertIsNone(self.ctl["rec"])
        self.restore.assert_called_once_with(0.8)
        stop.set.assert_called_once_with()
        stream._thread.join.assert_called_once_with(
            timeout=stt_stream.ABORT_JOIN_S)
        stream._fn.assert_not_called()
        self.st.turn.return_value.transition.assert_called_once_with(
            "done", result="discarded — another turn is running")

    def test_busy_release_still_discards_its_detached_capture(self):
        stream, stop, streams = self.registered_stream()
        self.rec["t0"] = 8.0
        self.ctl["busy"].is_set.return_value = True
        self.assertEqual(self.handle({"cmd": "listen", "phase": "stop"}),
                         {"ok": False, "error": "busy"})
        self.assertEqual(streams, {})
        stop.set.assert_called_once_with()
        self.assert_audio_released()
        stream._fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
