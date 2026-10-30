"""AS1: watchdog owns admission until a worker successfully accepts it.

Only daemon functions are loaded. All processes, audio, threads, locks, state
and streaming boundaries are fake; real capture cleanup stays exercised.
"""
import ast
from contextlib import suppress
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import pipeline, stage_capture, stt_stream, voice_polish  # noqa: E402


class WatchdogReleaseHandoff(unittest.TestCase):
    def setUp(self):
        self.busy = mock.Mock()
        self.busy.is_set.return_value = False
        self.busy.set.side_effect = lambda: setattr(
            self.busy.is_set, "return_value", True)
        self.busy.clear.side_effect = lambda: setattr(
            self.busy.is_set, "return_value", False)
        self.proc = mock.Mock()
        self.proc.poll.return_value = None
        self.proc.wait.side_effect = lambda **_: setattr(
            self.proc.poll, "return_value", 0)
        self.out = mock.Mock(spec=pathlib.Path)
        self.out.exists.return_value = True
        self.out.stat.return_value.st_size = 80
        self.stop = mock.Mock()
        self.sampler = mock.Mock()
        self.rec = {"proc": self.proc, "out": self.out, "ducked_vol": 0.8,
                    "sampler_stop": self.stop, "sampler": self.sampler}
        self.speculation = mock.Mock()
        self.ctl = {"rec": self.rec, "rec_lock": mock.MagicMock(),
                    "busy": self.busy, "stop": mock.Mock(),
                    "turn": "watchdog-turn", "spec": self.speculation}
        self.state = mock.Mock()
        self.thread = mock.Mock()
        self.thread_factory = mock.Mock(return_value=self.thread)
        self.record_stop = mock.Mock(wraps=pipeline.record_stop)
        self.run_listen = mock.Mock(
            side_effect=AssertionError("worker must never run in this test"))
        self.namespace = {
            "_DAEMON_CTL": self.ctl, "_DAEMON_ST": self.state,
            "_DAEMON_CFG": {"fake": "cfg"},
            "threading": types.SimpleNamespace(Thread=self.thread_factory),
            "pipeline": types.SimpleNamespace(record_stop=self.record_stop),
            "_run_listen": self.run_listen, "dlog": mock.Mock(),
            "suppress": suppress,
        }
        source = (pathlib.Path(__file__).resolve().parent.parent / "wispd").read_text()
        tree = ast.parse(source)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ("_rec_watchdog", "_drop_speculation")]
        self.assertEqual(len(functions), 2)
        exec(compile(ast.Module(body=functions, type_ignores=[]), "wispd", "exec"),
             self.namespace)
        self.watchdog = self.namespace["_rec_watchdog"]
        self.stream = mock.Mock()
        self.streams = {str(self.out): self.stream}
        self.patch(stt_stream, "_STREAMS", self.streams)
        self.restore = self.patch(voice_polish, "restore_speaker")
        self.patch(pipeline.subprocess, "Popen",
                   side_effect=AssertionError("real process forbidden"))
        self.patch(pipeline.subprocess, "run",
                   side_effect=AssertionError("real command forbidden"))

    def patch(self, obj, name, *args, **kwargs):
        p = mock.patch.object(obj, name, *args, **kwargs)
        value = p.start()
        self.addCleanup(p.stop)
        return value

    def assert_discarded_once(self):
        self.assertIsNone(self.ctl["rec"])
        self.assertEqual(self.streams, {})
        self.stream.abort.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.speculation.cancel.assert_called_once_with()

    def test_stop_runtime_error_releases_watchdog_admission(self):
        failure = RuntimeError("record_stop failed")
        self.proc.wait.side_effect = [failure, None]
        self.watchdog(self.ctl, 60)
        self.assertFalse(self.busy.is_set())
        self.busy.clear.assert_called_once_with()
        self.state.transition.assert_called_once_with(
            "error", error="record_stop failed")
        self.thread_factory.assert_not_called()
        self.assert_discarded_once()

    def test_stop_os_error_releases_admission_preserving_original(self):
        failure = OSError("recorder wait failed")
        self.proc.wait.side_effect = [failure, None]
        with self.assertRaises(OSError) as caught:
            self.watchdog(self.ctl, 60)
        self.assertIs(caught.exception, failure)
        self.assertFalse(self.busy.is_set())
        self.busy.clear.assert_called_once_with()
        self.state.transition.assert_not_called()
        self.thread_factory.assert_not_called()
        self.assert_discarded_once()

    def test_worker_start_failure_discards_stopped_unclaimed_stream(self):
        self.thread.start.side_effect = RuntimeError("cannot start worker")
        self.watchdog(self.ctl, 60)
        self.assertFalse(self.busy.is_set())
        self.busy.clear.assert_called_once_with()
        self.state.transition.assert_called_once_with(
            "error", error="cannot start worker")
        self.assertEqual(self.record_stop.call_args_list, [
            mock.call(self.rec, self.state.turn.return_value),
            mock.call(self.rec, self.state.turn.return_value, discard=True),
        ])
        self.proc.send_signal.assert_called_once()
        self.proc.wait.assert_called_once_with(timeout=3)
        self.proc.kill.assert_not_called()
        self.assert_discarded_once()

    def test_worker_construction_failure_releases_admission(self):
        failure = OSError("worker allocation failed")
        self.thread_factory.side_effect = failure
        with self.assertRaises(OSError) as caught:
            self.watchdog(self.ctl, 60)
        self.assertIs(caught.exception, failure)
        self.assertFalse(self.busy.is_set())
        self.busy.clear.assert_called_once_with()
        self.thread.start.assert_not_called()
        self.assert_discarded_once()

    def test_handoff_interruption_releases_only_untransferred_admission(self):
        failure = KeyboardInterrupt("worker handoff interrupted")
        self.thread.start.side_effect = failure
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.watchdog(self.ctl, 60)
        self.assertIs(caught.exception, failure)
        self.assertFalse(self.busy.is_set())
        self.busy.clear.assert_called_once_with()
        self.assert_discarded_once()

    def test_cleanup_failures_do_not_hide_original_handoff_failure(self):
        failure = OSError("original handoff failure")
        self.thread.start.side_effect = failure
        self.stream.abort.side_effect = RuntimeError("abort failed")
        self.speculation.cancel.side_effect = OSError("spec cleanup failed")
        with self.assertRaises(OSError) as caught:
            self.watchdog(self.ctl, 60)
        self.assertIs(caught.exception, failure)
        self.assertFalse(self.busy.is_set())
        self.busy.clear.assert_called_once_with()
        self.assert_discarded_once()

    def test_already_busy_discards_capture_but_preserves_other_admission(self):
        self.busy.is_set.return_value = True
        self.watchdog(self.ctl, 60)
        self.assertTrue(self.busy.is_set())
        self.busy.set.assert_not_called()
        self.busy.clear.assert_not_called()
        self.thread_factory.assert_not_called()
        self.record_stop.assert_called_once_with(
            self.rec, self.state.turn.return_value, discard=True)
        self.assertEqual(self.streams, {})
        self.restore.assert_called_once_with(0.8)
        self.speculation.cancel.assert_not_called()
        self.assertIs(self.ctl["spec"], self.speculation)

    def test_rejected_stop_error_never_clears_other_admission(self):
        self.busy.is_set.return_value = True
        failure = OSError("rejected recorder failed")
        self.proc.wait.side_effect = [failure, None]
        with self.assertRaises(OSError) as caught:
            self.watchdog(self.ctl, 60)
        self.assertIs(caught.exception, failure)
        self.assertTrue(self.busy.is_set())
        self.busy.set.assert_not_called()
        self.busy.clear.assert_not_called()
        self.thread_factory.assert_not_called()
        self.assertEqual(self.streams, {})
        self.restore.assert_called_once_with(0.8)
        self.speculation.cancel.assert_not_called()
        self.assertIs(self.ctl["spec"], self.speculation)

    def test_successful_start_transfers_admission_and_keeps_stream_claimable(self):
        self.watchdog(self.ctl, 60)
        self.assertTrue(self.busy.is_set())
        self.busy.set.assert_called_once_with()
        self.busy.clear.assert_not_called()
        self.thread_factory.assert_called_once_with(
            target=self.run_listen,
            args=(self.state, {"fake": "cfg"}, self.ctl, self.out,
                  None, "watchdog-turn"), daemon=True)
        self.thread.start.assert_called_once_with()
        self.record_stop.assert_called_once_with(
            self.rec, self.state.turn.return_value)
        self.assertIs(self.streams[str(self.out)], self.stream)
        self.stream.abort.assert_not_called()
        self.restore.assert_called_once_with(0.8)
        self.speculation.cancel.assert_not_called()
        self.run_listen.assert_not_called()

    def test_empty_audio_releases_admission_without_double_restoration(self):
        self.out.stat.return_value.st_size = 44
        self.watchdog(self.ctl, 60)
        self.assertFalse(self.busy.is_set())
        self.busy.clear.assert_called_once_with()
        self.thread_factory.assert_not_called()
        self.assert_discarded_once()
        self.assertIn("produced no audio",
                      self.state.transition.call_args.kwargs["error"])

    def test_no_capture_acquires_no_admission(self):
        self.ctl["rec"] = None
        self.watchdog(self.ctl, 60)
        self.busy.set.assert_not_called()
        self.busy.clear.assert_not_called()
        self.record_stop.assert_not_called()
        self.thread_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
