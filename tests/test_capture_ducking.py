"""U14 capture ownership regressions. All audio, processes, files and threads
are fakes; these tests must never change the machine's speaker volume."""
import pathlib
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import config, pipeline, platform, stage_capture, stt_stream, voice_polish


class SpeakerDucking(unittest.TestCase):
    def setUp(self):
        for patch in (
                mock.patch.object(voice_polish.shutil, "which",
                                  return_value="/fake/wpctl"),
                mock.patch.object(voice_polish.subprocess, "run",
                                  side_effect=AssertionError(
                                      "real command forbidden"))):
            patch.start()
            self.addCleanup(patch.stop)

    def test_missing_or_timed_out_command_is_best_effort(self):
        for failure in (OSError("no executable"),
                        subprocess.TimeoutExpired("fake wpctl", 1.5)):
            with self.subTest(failure=type(failure).__name__), \
                 mock.patch.object(voice_polish.subprocess, "run",
                                   side_effect=failure) as run:
                self.assertIsNone(voice_polish.duck_speaker({}))
                run.assert_called_once()

    def test_disabled_ducking_never_probes(self):
        for flag in ("false", "off", "0", False):
            with self.subTest(flag=flag):
                run = mock.Mock()
                self.assertIsNone(voice_polish.duck_speaker(
                    {"audio": {"duck_while_listening": flag}}, runner=run))
                run.assert_not_called()

    def test_muted_low_or_failed_probe_never_sets_volume(self):
        for rc, output in ((0, "Volume: 0.80 [MUTED]\n"),
                           (0, "Volume: 0.00"), (0, "Volume: 0.15"),
                           (0, "Volume: 0.08"), (1, "Volume: 0.80")):
            with self.subTest(rc=rc, output=output):
                run = mock.Mock(return_value=(rc, output))
                self.assertIsNone(voice_polish.duck_speaker({}, runner=run))
                run.assert_called_once_with(
                    ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])

    def test_missing_wpctl_never_runs_a_command(self):
        with mock.patch.object(voice_polish.shutil, "which",
                               return_value=None), \
             mock.patch.object(voice_polish, "_run") as run:
            self.assertIsNone(voice_polish.duck_speaker({}))
            voice_polish.restore_speaker(0.8)
        run.assert_not_called()

    def test_successful_duck_restores_the_saved_volume(self):
        for volume, target in (("0.80", "0.16"), ("0.20", "0.08"),
                               ("1.50", "0.30")):
            with self.subTest(volume=volume):
                run = mock.Mock(side_effect=[(0, f"Volume: {volume}\n"),
                                            (0, ""), (0, "")])
                saved = voice_polish.duck_speaker({}, runner=run)
                self.assertEqual(saved, float(volume))
                voice_polish.restore_speaker(saved, runner=run)
                self.assertEqual(run.call_args_list, [
                    mock.call(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]),
                    mock.call(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@",
                               target]),
                    mock.call(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@",
                               volume]),
                ])

    def test_no_restore_token_does_not_probe(self):
        run = mock.Mock()
        voice_polish.restore_speaker(None, runner=run)
        run.assert_not_called()

    def test_malformed_volume_never_changes_the_sink(self):
        for output in ("", "not volume", "Volume: .", "Volume: 0..8",
                       "Volume: 0.8.2", "Volume: 0.80garbage",
                       "Volume: nan", "Volume: inf", "Volume: -0.8",
                       "Volume: " + "9" * 400):
            with self.subTest(output=output):
                run = mock.Mock(return_value=(0, output))
                self.assertIsNone(voice_polish.duck_speaker({}, runner=run))
                run.assert_called_once_with(
                    ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])

    def test_failed_set_does_not_claim_a_restore_token(self):
        run = mock.Mock(side_effect=[(0, "Volume: 0.80\n"),
                                    (1, "sink unavailable")])
        self.assertIsNone(voice_polish.duck_speaker({}, runner=run))
        self.assertEqual(run.call_args_list, [
            mock.call(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]),
            mock.call(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.16"]),
        ])


class CaptureOwnership(unittest.TestCase):
    def setUp(self):
        self.out = mock.Mock(spec=pathlib.Path)
        self.out.exists.return_value = True
        self.out.stat.return_value = SimpleNamespace(st_size=400)
        self.cfg_dir = mock.MagicMock(spec=pathlib.Path)
        self.cfg_dir.__truediv__.return_value = self.out
        self.proc = mock.Mock()
        self.proc.poll.return_value = None
        self.sampler = mock.Mock()
        self.stop = mock.Mock()
        self.state = mock.Mock()
        self.real_spawn = voice_polish.spawn_recorder
        self.spawn = self.patch(voice_polish, "spawn_recorder",
                               return_value=(self.proc, False))
        self.restore = self.patch(voice_polish, "restore_speaker")
        self.duck = self.patch(voice_polish, "duck_speaker", return_value=0.8)
        self.patch(config, "CFG_DIR", self.cfg_dir)
        self.patch(config, "RUN_DIR", mock.Mock(spec=pathlib.Path))
        self.patch(config, "LEVEL_FILE", mock.Mock(spec=pathlib.Path))
        self.load_config = self.patch(config, "load_config", return_value={})
        self.thread = self.patch(stage_capture.threading, "Thread",
                                 return_value=self.sampler)
        self.event = self.patch(stage_capture.threading, "Event",
                                return_value=self.stop)
        self.env = self.patch(pipeline, "hypr_env", return_value={"FAKE": "yes"})
        self.popen = self.patch(pipeline.subprocess, "Popen",
                               side_effect=AssertionError(
                                   "real process forbidden"))
        self.patch(pipeline.subprocess, "run",
                   side_effect=AssertionError("real command forbidden"))
        self.patch(pipeline.time, "sleep",
                   side_effect=AssertionError("real sleep forbidden"))
        self.begin = self.patch(stt_stream, "begin")
        self.record_cmd = self.patch(platform, "record_cmd",
                                     return_value=["fake-recorder"])
        self.notify = self.patch(pipeline, "notify")

    def patch(self, obj, name, *args, **kwargs):
        p = mock.patch.object(obj, name, *args, **kwargs)
        value = p.start()
        self.addCleanup(p.stop)
        return value

    def test_stream_start_failure_rolls_back_capture(self):
        failure = RuntimeError("stream startup failed")
        self.begin.side_effect = failure
        with self.assertRaises(RuntimeError) as caught:
            pipeline.record_start(self.state)
        self.assertIs(caught.exception, failure)
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.proc.kill.assert_called_once_with()
        self.proc.wait.assert_called_once_with(timeout=3)
        self.state.set_level.assert_called_once_with(0.0)

    def test_partially_registered_stream_is_discarded_on_startup_failure(self):
        stream = mock.Mock()
        streams = {}
        self.patch(stt_stream, "_STREAMS", streams)
        failure = RuntimeError("partial begin failed")

        def partial_begin(out, proc):
            streams[str(out)] = stream
            raise failure

        self.begin.side_effect = partial_begin
        with self.assertRaises(RuntimeError) as caught:
            pipeline.record_start(self.state)
        self.assertIs(caught.exception, failure)
        self.assertEqual(streams, {})
        stream.abort.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)
        self.proc.kill.assert_called_once_with()
        self.stop.set.assert_called_once_with()

    def test_duplicate_finish_releases_owned_state_once(self):
        rec = pipeline.record_start(self.state)
        self.proc.poll.return_value = 0
        self.assertIs(pipeline.record_stop(rec, self.state), self.out)
        self.assertIs(pipeline._record_finish(rec, self.state), self.out)
        self.restore.assert_called_once_with(0.8)
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.state.set_level.assert_called_once_with(0.0)

    def test_stop_interruption_releases_capture_before_reraising(self):
        rec = pipeline.record_start(self.state)
        failure = KeyboardInterrupt("interrupted while waiting")
        self.proc.wait.side_effect = [failure, None]
        with self.assertRaises(KeyboardInterrupt) as caught:
            pipeline.record_stop(rec, self.state)
        self.assertIs(caught.exception, failure)
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.proc.kill.assert_called_once_with()
        self.state.set_level.assert_called_once_with(0.0)

    def test_bounded_wait_interruption_releases_capture(self):
        failure = KeyboardInterrupt("bounded wait interrupted")
        self.proc.wait.side_effect = [failure, None]
        with self.assertRaises(KeyboardInterrupt) as caught:
            pipeline.record(2, self.state)
        self.assertIs(caught.exception, failure)
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.proc.kill.assert_called_once_with()
        self.state.set_level.assert_called_once_with(0.0)

    def test_normal_stop_restores_after_signalling_the_recorder(self):
        rec = pipeline.record_start(self.state)
        self.restore.assert_not_called()
        self.begin.assert_called_once_with(self.out, self.proc)
        self.assertEqual(rec["ducked_vol"], 0.8)
        self.assertIs(pipeline.record_stop(rec, self.state), self.out)
        self.proc.send_signal.assert_called_once_with(stage_capture.signal.SIGINT)
        self.proc.wait.assert_called_once_with(timeout=3)
        self.proc.kill.assert_not_called()
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.state.set_level.assert_called_once_with(0.0)

    def test_bounded_completion_restores_without_signalling(self):
        self.assertIs(pipeline.record(2, self.state), self.out)
        self.proc.wait.assert_called_once_with(timeout=2)
        self.proc.send_signal.assert_not_called()
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()

    def test_bounded_timeout_preserves_pipeline_stop_patch_seam(self):
        self.proc.wait.side_effect = subprocess.TimeoutExpired("fake", 2)
        sentinel = object()
        with mock.patch.object(pipeline, "record_stop",
                               return_value=sentinel) as stop:
            self.assertIs(pipeline.record(2, self.state), sentinel)
        stop.assert_called_once()
        self.assertIs(stop.call_args.args[0]["proc"], self.proc)
        self.assertIs(stop.call_args.args[1], self.state)

    def test_bounded_timeout_releases_capture(self):
        self.proc.wait.side_effect = [subprocess.TimeoutExpired("fake", 2), None]
        self.assertIs(pipeline.record(2, self.state), self.out)
        self.assertEqual(self.proc.wait.call_args_list,
                         [mock.call(timeout=2), mock.call(timeout=3)])
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()

    def test_stop_timeout_kills_then_restores(self):
        rec = pipeline.record_start(self.state)
        self.proc.wait.side_effect = [subprocess.TimeoutExpired("fake", 3), None]
        self.assertIs(pipeline.record_stop(rec, self.state), self.out)
        self.proc.kill.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()

    def test_stop_second_timeout_does_not_hide_original_error(self):
        rec = pipeline.record_start(self.state)
        failure = subprocess.TimeoutExpired("fake", 3)
        self.proc.wait.side_effect = [subprocess.TimeoutExpired("fake", 3),
                                      failure, OSError("reap failed")]
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            pipeline.record_stop(rec, self.state)
        self.assertIs(caught.exception, failure)
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.state.set_level.assert_called_once_with(0.0)

    def test_signal_failure_still_releases_capture(self):
        rec = pipeline.record_start(self.state)
        failure = OSError("cannot signal")
        self.proc.send_signal.side_effect = failure
        with self.assertRaises(OSError) as caught:
            pipeline.record_stop(rec, self.state)
        self.assertIs(caught.exception, failure)
        self.proc.kill.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()

    def test_missing_or_empty_audio_is_reported_after_cleanup(self):
        for exists, size in ((False, 0), (True, 0), (True, 44)):
            with self.subTest(exists=exists, size=size):
                rec = pipeline.record_start(self.state)
                self.out.exists.return_value = exists
                self.out.stat.return_value.st_size = size
                self.proc.poll.return_value = 0
                with self.assertRaisesRegex(RuntimeError, "produced no audio"):
                    pipeline.record_stop(rec, self.state)
                self.assertNotIn("ducked_vol", rec)
        self.assertEqual(self.restore.call_args_list, [mock.call(0.8)] * 3)
        self.assertEqual(self.stop.set.call_count, 3)

    def test_sampler_start_failure_restores_volume(self):
        failure = RuntimeError("thread did not start")
        self.sampler.start.side_effect = failure
        self.sampler.join.side_effect = RuntimeError("not started")
        with self.assertRaises(RuntimeError) as caught:
            pipeline.record_start(self.state)
        self.assertIs(caught.exception, failure)
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.spawn.assert_not_called()
        self.state.set_level.assert_called_once_with(0.0)

    def test_sampler_construction_failure_restores_volume(self):
        self.thread.side_effect = RuntimeError("no thread")
        with self.assertRaisesRegex(RuntimeError, "no thread"):
            pipeline.record_start(self.state)
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.spawn.assert_not_called()

    def test_environment_failure_restores_volume(self):
        self.env.side_effect = OSError("no session")
        with self.assertRaisesRegex(OSError, "no session"):
            pipeline.record_start(self.state)
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.spawn.assert_not_called()

    def test_recorder_spawn_failure_restores_volume(self):
        self.spawn.side_effect = OSError("recorder not available")
        with self.assertRaisesRegex(OSError, "recorder not available"):
            pipeline.record_start(self.state)
        self.restore.assert_called_once_with(0.8)
        self.stop.set.assert_called_once_with()
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.begin.assert_not_called()

    def test_cleanup_failures_do_not_replace_stream_start_error(self):
        failure = RuntimeError("original stream error")
        self.begin.side_effect = failure
        self.proc.kill.side_effect = OSError("kill failed")
        self.proc.wait.side_effect = OSError("reap failed")
        self.stop.set.side_effect = RuntimeError("stop failed")
        self.restore.side_effect = OSError("restore failed")
        self.sampler.join.side_effect = RuntimeError("join failed")
        self.state.set_level.side_effect = OSError("state failed")
        with self.assertRaises(RuntimeError) as caught:
            pipeline.record_start(self.state)
        self.assertIs(caught.exception, failure)
        self.proc.kill.assert_called_once_with()
        self.proc.wait.assert_called_once_with(timeout=3)
        self.stop.set.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)
        self.state.set_level.assert_called_once_with(0.0)

    def test_cleanup_failures_do_not_skip_audio_validation(self):
        rec = pipeline.record_start(self.state)
        self.out.stat.return_value.st_size = 44
        self.restore.side_effect = OSError("restore failed")
        self.sampler.join.side_effect = RuntimeError("join failed")
        self.state.set_level.side_effect = OSError("state failed")
        with self.assertRaisesRegex(RuntimeError, "produced no audio"):
            pipeline._record_finish(rec, self.state)
        with self.assertRaisesRegex(RuntimeError, "produced no audio"):
            pipeline._record_finish(rec, self.state)
        self.restore.assert_called_once_with(0.8)
        self.state.set_level.assert_called_once_with(0.0)

    def test_finish_without_state_resets_only_the_fake_level_file(self):
        rec = pipeline.record_start()
        self.proc.poll.return_value = 0
        self.assertIs(pipeline.record_stop(rec), self.out)
        config.LEVEL_FILE.write_text.assert_called_once_with("0.0")
        self.restore.assert_called_once_with(0.8)

    def real_retry(self):
        self.load_config.return_value = {"audio": {"device": "missing-usb"}}
        self.spawn.side_effect = lambda cmd, spawn, **kw: self.real_spawn(
            cmd, spawn, sleep=lambda _: None, **kw)

    def test_failed_default_retry_releases_sampler(self):
        self.real_retry()
        dead = mock.Mock()
        dead.poll.return_value = 1
        self.popen.side_effect = [dead, OSError("default failed")]
        with self.assertRaisesRegex(OSError, "default failed"):
            pipeline.record_start(self.state)
        self.assertEqual(self.popen.call_count, 2)
        dead.wait.assert_called_once_with(timeout=3)
        self.stop.set.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)
        self.sampler.join.assert_called_once_with(
            timeout=stage_capture._SAMPLER_JOIN_S)

    def test_successful_default_retry_keeps_handle_until_stop(self):
        self.real_retry()
        dead = mock.Mock()
        dead.poll.return_value = 1
        self.popen.side_effect = [dead, self.proc]
        rec = pipeline.record_start(self.state)
        self.assertIs(rec["proc"], self.proc)
        self.restore.assert_not_called()
        self.assertEqual(self.record_cmd.call_args_list[-2:], [
            mock.call(self.out, None, "missing-usb"),
            mock.call(self.out, None, ""),
        ])
        self.notify.assert_called_once()
        self.assertIs(pipeline.record_stop(rec, self.state), self.out)
        self.restore.assert_called_once_with(0.8)

    def test_device_settling_interruption_reaps_the_spawned_recorder(self):
        self.load_config.return_value = {"audio": {"device": "usb"}}
        failure = KeyboardInterrupt("interrupted during device settling")
        self.spawn.side_effect = lambda cmd, spawn, **kw: self.real_spawn(
            cmd, spawn, sleep=mock.Mock(side_effect=failure), **kw)
        self.popen.side_effect = None
        self.popen.return_value = self.proc
        with self.assertRaises(KeyboardInterrupt) as caught:
            pipeline.record_start(self.state)
        self.assertIs(caught.exception, failure)
        self.proc.kill.assert_called_once_with()
        self.proc.wait.assert_called_once_with(timeout=3)
        self.stop.set.assert_called_once_with()
        self.restore.assert_called_once_with(0.8)

    def test_event_creation_failure_restores_volume(self):
        self.event.side_effect = RuntimeError("no event")
        with self.assertRaisesRegex(RuntimeError, "no event"):
            pipeline.record_start(self.state)
        self.restore.assert_called_once_with(0.8)
        self.thread.assert_not_called()
        self.spawn.assert_not_called()

    def test_unavailable_recorder_never_ducks(self):
        self.record_cmd.return_value = None
        self.patch(platform, "missing_deps_hint", return_value="fake hint")
        with self.assertRaisesRegex(RuntimeError, "no recorder found"):
            pipeline.record_start(self.state)
        self.duck.assert_not_called()
        self.thread.assert_not_called()


class SamplerOwnership(unittest.TestCase):
    def test_cancel_during_read_never_publishes_a_late_level(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        stop = mock.Mock()
        stop.is_set.return_value = False

        def last_window(_):
            stop.is_set.return_value = True
            return b"\xff" * stage_capture._LEVEL_WINDOW

        proc.stdout.read.side_effect = last_window
        state = mock.Mock()
        with mock.patch.object(platform, "sampler_cmd", return_value=["fake"]), \
             mock.patch.object(pipeline, "hypr_env", return_value={}), \
             mock.patch.object(pipeline.subprocess, "Popen", return_value=proc):
            pipeline._amplitude_sampler(None, state, stop)
        state.set_level.assert_not_called()
        proc.kill.assert_called_once_with()
        proc.wait.assert_called_once_with(timeout=5)

    def test_failed_read_still_reaps_the_sampler_process(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.stdout.read.side_effect = OSError("sampler pipe failed")
        state = mock.Mock()
        with mock.patch.object(platform, "sampler_cmd", return_value=["fake"]), \
             mock.patch.object(pipeline, "hypr_env", return_value={}), \
             mock.patch.object(pipeline.subprocess, "Popen", return_value=proc):
            pipeline._amplitude_sampler(None, state)
        proc.kill.assert_called_once_with()
        proc.wait.assert_called_once_with(timeout=5)
        state.set_level.assert_called_once_with(0.0)


if __name__ == "__main__":
    unittest.main()
