#!/usr/bin/env python3
"""Cancellable turns and prompt ids (backend U9).

Everything runs against loopback fakes and throwaway shell scripts; no
audio is played (the TTS command is a script that appends to a log), no
paid call is made and no live service is touched.
"""
import http.client
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import fakes  # noqa: E402
from wisp import act, brain, cancel, config, pipeline, speech, tools  # noqa: E402


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie still answers kill(0)
        return pathlib.Path(f"/proc/{pid}/stat").read_text() \
            .rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _after(sec, fn):
    t = threading.Timer(sec, fn)
    t.daemon = True
    t.start()
    return t


class CancelTokenTest(unittest.TestCase):
    def test_cancel_sets_flag_once_and_check_raises(self):
        tok = cancel.CancelToken()
        self.assertFalse(tok.cancelled)
        tok.check()  # no raise
        tok.cancel()
        tok.cancel()  # idempotent
        self.assertTrue(tok.cancelled)
        with self.assertRaises(cancel.Cancelled) as cm:
            tok.check()
        self.assertEqual(cm.exception.code, "cancelled")

    def test_cancel_kills_registered_pid(self):
        tok = cancel.CancelToken()
        proc = subprocess.Popen(["sleep", "30"])
        tok.register_pid(proc)
        t = time.monotonic()
        tok.cancel()
        proc.wait(timeout=2)
        self.assertLess(time.monotonic() - t, 0.5)
        self.assertFalse(_alive(proc.pid))

    def test_unregistered_pid_is_left_alone(self):
        tok = cancel.CancelToken()
        proc = subprocess.Popen(["sleep", "30"])
        self.addCleanup(proc.kill)
        tok.register_pid(proc)
        tok.unregister_pid(proc)
        tok.cancel()
        time.sleep(0.1)
        self.assertIsNone(proc.poll())

    def test_registering_after_cancel_acts_immediately(self):
        tok = cancel.CancelToken()
        tok.cancel()
        proc = subprocess.Popen(["sleep", "30"])
        tok.register_pid(proc)
        proc.wait(timeout=2)
        seen = []
        tok.register_close(lambda: seen.append(1))
        self.assertEqual(seen, [1])

    def test_close_callbacks_run_on_cancel(self):
        tok = cancel.CancelToken()
        seen = []
        tok.register_close(lambda: seen.append("a"))
        h = tok.register_close(lambda: seen.append("b"))
        tok.unregister_close(h)
        tok.cancel()
        self.assertEqual(seen, ["a"])

    def test_wait_returns_early_on_cancel(self):
        tok = cancel.CancelToken()
        _after(0.05, tok.cancel)
        t = time.monotonic()
        self.assertTrue(tok.wait(2))
        self.assertLess(time.monotonic() - t, 0.5)

    def test_bind_sets_and_restores_current(self):
        self.assertIsNone(cancel.current())
        tok = cancel.CancelToken()
        with cancel.bind(tok):
            self.assertIs(cancel.current(), tok)
            self.assertFalse(cancel.is_cancelled())
            tok.cancel()
            self.assertTrue(cancel.is_cancelled())
        self.assertIsNone(cancel.current())


class CancelRunTest(unittest.TestCase):
    def test_without_a_token_it_is_subprocess_run(self):
        with mock.patch("subprocess.run", return_value="sentinel") as run:
            self.assertEqual(cancel.run(["echo", "x"], capture_output=True),
                             "sentinel")
        run.assert_called_once()

    def test_runs_normally_under_a_token(self):
        with cancel.bind(cancel.CancelToken()):
            r = cancel.run("echo hi", shell=True, capture_output=True,
                           text=True, timeout=5)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "hi")

    def test_cancel_kills_the_child_promptly(self):
        tok = cancel.CancelToken()
        pidfile = pathlib.Path(tempfile.mkdtemp()) / "pid"
        _after(0.1, tok.cancel)
        t = time.monotonic()
        with cancel.bind(tok), self.assertRaises(cancel.Cancelled):
            cancel.run(f"echo $$ > {pidfile}; exec sleep 30", shell=True,
                       capture_output=True)
        self.assertLess(time.monotonic() - t, 0.4)
        self.assertFalse(_alive(int(pidfile.read_text())))

    def test_timeout_still_raises_timeout_expired(self):
        with cancel.bind(cancel.CancelToken()), \
                self.assertRaises(subprocess.TimeoutExpired):
            cancel.run(["sleep", "5"], timeout=0.2)


class WhisperCliCancelTest(unittest.TestCase):
    """Cancel during STT kills the whisper-cli subprocess."""

    def test_cancel_during_local_stt_kills_whisper_cli(self):
        d = pathlib.Path(tempfile.mkdtemp())
        pidfile = d / "pid"
        fake = d / "whisper-cli"
        fake.write_text(f"#!/bin/sh\necho $$ > {pidfile}\nexec sleep 30\n")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        model = d / "model.bin"
        model.write_bytes(b"x")
        wav = d / "a.wav"
        wav.write_bytes(b"RIFF")
        tok = cancel.CancelToken()
        _after(0.15, tok.cancel)
        t = time.monotonic()
        with mock.patch.object(config, "WHISPER_BIN", fake), \
                mock.patch.object(config, "whisper_model",
                                  return_value=model), \
                cancel.bind(tok), self.assertRaises(cancel.Cancelled):
            pipeline.transcribe(wav, {"stt": {"provider": "local"}})
        self.assertLess(time.monotonic() - t, 0.4)
        self.assertFalse(_alive(int(pidfile.read_text())))


class HttpCancelTest(unittest.TestCase):
    def test_cancel_during_jev_closes_the_connection(self):
        with fakes.FakeJev({"answers": {"route": {"choice": "answer"}},
                            "latency_ms": 700}) as srv:
            tok = cancel.CancelToken()
            _after(0.1, tok.cancel)
            t = time.monotonic()
            with mock.patch.object(config, "JEV_ENDPOINT",
                                   srv.url + "/api/alpha/decisions"), \
                    cancel.bind(tok), self.assertRaises(cancel.Cancelled):
                pipeline.ask_jev("hi", "m", {})
            self.assertLess(time.monotonic() - t, 0.4)
            time.sleep(0.8)  # let the fake finish its latency
            self.assertTrue(srv.peer_closed,
                            "the fake never saw the client hang up")

    def test_cancel_during_openai_stt_closes_the_connection(self):
        d = pathlib.Path(tempfile.mkdtemp())
        wav = d / "a.wav"
        wav.write_bytes(b"RIFF" + b"\0" * 64)
        with fakes.FakeWhisper({"transcript": "x", "latency_ms": 600}) \
                as srv:
            tok = cancel.CancelToken()
            _after(0.1, tok.cancel)
            cfg = {"stt": {"provider": "openai", "base_url": srv.url,
                           "model": "m", "key_env": "WISP_U9_KEY"}}
            t = time.monotonic()
            with mock.patch.dict(os.environ, {"WISP_U9_KEY": "k"}), \
                    cancel.bind(tok), self.assertRaises(cancel.Cancelled):
                pipeline.transcribe(wav, cfg)
            self.assertLess(time.monotonic() - t, 0.4)
            time.sleep(0.7)
            self.assertTrue(srv.peer_closed)

    def test_already_cancelled_token_never_dials(self):
        tok = cancel.CancelToken()
        tok.cancel()
        with cancel.bind(tok), self.assertRaises(cancel.Cancelled):
            cancel.urlopen(urllib.request.Request("http://127.0.0.1:9/x"))


def _brain_cfg(primary_url, fallback_url=None, **brain_extra):
    cfg = {"brain": {"default": "openai_compat:fake", **brain_extra},
           "brain.openai_compat": {"base_url": primary_url + "/v1",
                                   "key_env": "", "tools": "true"}}
    if fallback_url:
        cfg["brain"]["fallback"] = "fb:fake2"
        cfg["brain.fb"] = {"base_url": fallback_url + "/v1",
                           "key_env": "", "tools": "true"}
    return cfg


class BrainStreamCancelTest(unittest.TestCase):
    CHUNKS = ["One ", "two ", "three ", "four ", "five ", "six ",
              "seven."]

    def test_cancel_mid_stream_stops_deltas_and_closes_socket(self):
        script = {"responses": [{"chunks": self.CHUNKS,
                                 "chunk_delay_ms": 100}]}
        with fakes.FakeBrain(script) as srv:
            tok = cancel.CancelToken()
            seen = []
            fired = []

            def on_delta(acc):
                seen.append((time.monotonic(), acc))

            def fire():
                fired.append(time.monotonic())
                tok.cancel()
            _after(0.25, fire)
            with cancel.bind(tok), self.assertRaises(cancel.Cancelled):
                brain.chat_stream([{"role": "user", "content": "x"}],
                                  _brain_cfg(srv.url), on_delta=on_delta)
            self.assertTrue(seen, "nothing streamed before the cancel")
            self.assertLess(seen[-1][0], fired[0] + 0.05,
                            "delta delivered after the cancel")
            self.assertLess(len(seen), len(self.CHUNKS))
            time.sleep(0.3)
            self.assertTrue(srv.peer_closed)
            self.assertLess(len(srv.sent), len(self.CHUNKS))

    def test_cancelled_turn_never_falls_back_to_the_next_brain(self):
        script1 = {"responses": [{"chunks": self.CHUNKS,
                                  "chunk_delay_ms": 100}]}
        script2 = {"responses": [{"chunks": ["fallback answer"]}]}
        with fakes.FakeBrain(script1) as a, fakes.FakeBrain(script2) as b:
            tok = cancel.CancelToken()
            _after(0.25, tok.cancel)
            with cancel.bind(tok), self.assertRaises(cancel.Cancelled):
                brain.chat_stream([{"role": "user", "content": "x"}],
                                  _brain_cfg(a.url, b.url),
                                  on_delta=lambda acc: None)
            time.sleep(0.2)
            self.assertEqual(
                [c for c in b.calls
                 if c["path"].endswith("/chat/completions")], [])

    def test_cancel_before_first_token_does_not_fall_back(self):
        script1 = {"responses": [{"chunks": ["x"], "latency_ms": 800}]}
        script2 = {"responses": [{"chunks": ["fallback answer"]}]}
        with fakes.FakeBrain(script1) as a, fakes.FakeBrain(script2) as b:
            tok = cancel.CancelToken()
            _after(0.15, tok.cancel)
            t = time.monotonic()
            with cancel.bind(tok), self.assertRaises(cancel.Cancelled):
                brain.chat_stream([{"role": "user", "content": "x"}],
                                  _brain_cfg(a.url, b.url,
                                             first_token_s="5"),
                                  on_delta=lambda acc: None)
            self.assertLess(time.monotonic() - t, 0.5)
            time.sleep(0.1)
            self.assertEqual(
                [c for c in b.calls
                 if c["path"].endswith("/chat/completions")], [])

    def test_cancelled_non_streaming_chat_does_not_fall_back(self):
        script1 = {"responses": [{"content": "slow", "latency_ms": 800}]}
        script2 = {"responses": [{"content": "fallback"}]}
        with fakes.FakeBrain(script1) as a, fakes.FakeBrain(script2) as b:
            tok = cancel.CancelToken()
            _after(0.15, tok.cancel)
            with cancel.bind(tok), self.assertRaises(cancel.Cancelled):
                brain.chat([{"role": "user", "content": "x"}],
                           _brain_cfg(a.url, b.url))
            time.sleep(0.1)
            self.assertEqual(
                [c for c in b.calls
                 if c["path"].endswith("/chat/completions")], [])

    def test_uncancelled_stream_is_unchanged(self):
        script = {"responses": [{"chunks": ["Hi ", "there."]}]}
        with fakes.FakeBrain(script) as srv, \
                cancel.bind(cancel.CancelToken()):
            out = brain.chat_stream([{"role": "user", "content": "x"}],
                                    _brain_cfg(srv.url),
                                    on_delta=lambda acc: None)
        self.assertEqual(out["content"], "Hi there.")


class ActCancelTest(unittest.TestCase):
    CFG = {"agent": {"allow_shell": "true", "screenshots": "false"},
           "brain": {"default": "openai_compat:m"},
           "brain.openai_compat": {"base_url": "http://127.0.0.1:9/v1",
                                   "tools": "true", "vision": "false"}}

    def _call(self, name, arg=""):
        return {"id": f"c_{name}", "type": "function",
                "function": {"name": name,
                             "arguments": json.dumps({"arg": arg})}}

    def test_cancel_between_steps_runs_no_further_steps(self):
        tok = cancel.CancelToken()
        ran = []

        def fake_run(name, arg, cfg, harness=None):
            ran.append(name)
            tok.cancel()          # user hits stop during the first step
            return "OK"
        msgs = iter([{"role": "assistant", "content": None,
                      "tool_calls": [self._call("recall", "a"),
                                     self._call("recall", "b")]},
                     {"role": "assistant", "content": "done"}])
        with mock.patch.object(act, "_post",
                               side_effect=lambda m, c: next(msgs)), \
                mock.patch.object(tools, "run", fake_run), \
                mock.patch.object(act, "_gate", return_value=None), \
                cancel.bind(tok):
            out = act.run_act_loop("do two things", self.CFG)
        self.assertEqual(ran, ["recall"])
        self.assertTrue(out.startswith("INTERRUPTED"), out)

    def test_cancel_during_a_model_call_returns_promptly(self):
        tok = cancel.CancelToken()

        def slow_post(messages, cfg):
            tok.wait(5)
            raise cancel.Cancelled()
        _after(0.1, tok.cancel)
        t = time.monotonic()
        with mock.patch.object(act, "_post", slow_post), \
                cancel.bind(tok):
            out = act.run_act_loop("x", self.CFG)
        self.assertLess(time.monotonic() - t, 0.4)
        self.assertTrue(out.startswith("INTERRUPTED"), out)

    def test_cancel_kills_the_running_shell_step(self):
        tok = cancel.CancelToken()
        _after(0.15, tok.cancel)
        msgs = iter([{"role": "assistant", "content": None,
                      "tool_calls": [self._call("shell", "sleep 30")]},
                     {"role": "assistant", "content": "done"}])
        t = time.monotonic()
        with mock.patch.object(act, "_post",
                               side_effect=lambda m, c: next(msgs)), \
                mock.patch.object(act, "_gate", return_value=None), \
                cancel.bind(tok):
            out = act.run_act_loop("sleepy", self.CFG)
        self.assertLess(time.monotonic() - t, 0.5)
        self.assertTrue(out.startswith("INTERRUPTED"), out)


class PromptIdTest(unittest.TestCase):
    OPTS = ["app:discord", "app:browser", "action:launch"]

    def _wait_in_thread(self, broker, prompt_id="p1", options=None,
                        timeout=3, token=None):
        out = {}

        def run():
            out["pick"] = broker.waiter(token)(
                timeout, prompt_id=prompt_id, options=options or self.OPTS)
            out["t"] = time.monotonic()
        th = threading.Thread(target=run, daemon=True)
        th.start()
        for _ in range(200):
            if broker.pending_id == prompt_id:
                break
            time.sleep(0.005)
        return th, out

    def test_new_prompt_ids_are_unique(self):
        ids = {cancel.new_prompt_id() for _ in range(50)}
        self.assertEqual(len(ids), 50)

    def test_matching_id_resolves_the_wait(self):
        b = cancel.PromptBroker()
        th, out = self._wait_in_thread(b)
        r = b.offer(pick="app:browser", prompt_id="p1")
        th.join(2)
        self.assertEqual(r, {"ok": True})
        self.assertEqual(out["pick"], "app:browser")

    def test_previous_prompt_id_is_rejected_and_current_still_waits(self):
        b = cancel.PromptBroker()
        th, out = self._wait_in_thread(b, prompt_id="p2")
        r = b.offer(pick="app:discord", prompt_id="p1")
        self.assertEqual(r["ok"], False)
        self.assertEqual(r["error"], "stale_prompt")
        time.sleep(0.1)
        self.assertTrue(th.is_alive(), "stale pick resolved the prompt")
        self.assertEqual(b.pending_id, "p2")
        self.assertTrue(b.offer(pick="app:discord", prompt_id="p2")["ok"])
        th.join(2)
        self.assertEqual(out["pick"], "app:discord")

    def test_missing_id_accepted_while_exactly_one_prompt_pending(self):
        b = cancel.PromptBroker()
        th, out = self._wait_in_thread(b)
        self.assertTrue(b.offer(pick="action:launch")["ok"])
        th.join(2)
        self.assertEqual(out["pick"], "action:launch")

    def test_nothing_pending_is_stale_with_or_without_id(self):
        b = cancel.PromptBroker()
        self.assertEqual(b.offer(pick="app:x")["error"], "stale_prompt")
        self.assertEqual(b.offer(pick="app:x", prompt_id="p1")["error"],
                         "stale_prompt")

    def test_index_picks_the_nth_option_one_based(self):
        b = cancel.PromptBroker()
        th, out = self._wait_in_thread(b)
        self.assertTrue(b.offer(index=2, prompt_id="p1")["ok"])
        th.join(2)
        self.assertEqual(out["pick"], "app:browser")

    def test_index_out_of_range_is_rejected_and_prompt_stays(self):
        b = cancel.PromptBroker()
        th, out = self._wait_in_thread(b)
        for bad in (0, 4, -1):
            r = b.offer(index=bad, prompt_id="p1")
            self.assertEqual((r["ok"], r["error"]), (False, "bad_index"))
        time.sleep(0.05)
        self.assertTrue(th.is_alive())
        b.offer(index=1, prompt_id="p1")
        th.join(2)
        self.assertEqual(out["pick"], "app:discord")

    def test_unoffered_pick_is_rejected_and_prompt_stays(self):
        b = cancel.PromptBroker()
        th, out = self._wait_in_thread(b)
        r = b.offer(pick="app:ghostapp", prompt_id="p1")
        self.assertEqual((r["ok"], r["error"]), (False, "not_offered"))
        time.sleep(0.05)
        self.assertTrue(th.is_alive())
        b.offer(pick="app:discord", prompt_id="p1")
        th.join(2)

    def test_empty_pick_dismisses_the_prompt(self):
        b = cancel.PromptBroker()
        th, out = self._wait_in_thread(b)
        self.assertTrue(b.offer(pick="", prompt_id="p1")["ok"])
        th.join(2)
        self.assertIsNone(out["pick"])

    def test_timeout_returns_none_and_clears_pending(self):
        b = cancel.PromptBroker()
        pick = b.waiter()(0.1, prompt_id="p1", options=self.OPTS)
        self.assertIsNone(pick)
        self.assertEqual(b.pending_id, "")

    def test_cancel_wakes_the_waiter(self):
        b = cancel.PromptBroker()
        tok = cancel.CancelToken()
        th, out = self._wait_in_thread(b, token=tok, timeout=5)
        t = time.monotonic()
        tok.cancel()
        th.join(2)
        self.assertIsNone(out["pick"])
        self.assertLess(out["t"] - t, 0.3)


class WispdWiringTest(unittest.TestCase):
    def setUp(self):
        path = str(ROOT / "wispd")
        loader = importlib.machinery.SourceFileLoader("wispd_u9", path)
        spec = importlib.util.spec_from_loader("wispd_u9", loader)
        self.w = importlib.util.module_from_spec(spec)
        loader.exec_module(self.w)
        self.ctl = {"stop": threading.Event(), "busy": threading.Event(),
                    "interrupt": threading.Event(),
                    "choice_event": threading.Event(), "choice_pick": "",
                    "rec": None, "rec_lock": threading.Lock(),
                    "broker": cancel.PromptBroker(),
                    "token": cancel.CancelToken()}
        self.handle = self.w._handler(mock.Mock(), {}, self.ctl)

    def test_interrupt_sets_the_turn_token_and_the_legacy_event(self):
        proc = subprocess.Popen(["sleep", "30"])
        self.ctl["token"].register_pid(proc)
        with mock.patch.object(self.w.speech, "stop") as stop:
            self.assertEqual(self.handle({"cmd": "interrupt"}),
                             {"ok": True})
        stop.assert_called()
        self.assertTrue(self.ctl["token"].cancelled)
        self.assertTrue(self.ctl["interrupt"].is_set())
        proc.wait(timeout=2)

    def test_choice_passes_prompt_id_and_index_to_the_broker(self):
        th = threading.Thread(
            target=lambda: self.ctl.__setitem__(
                "got", self.ctl["broker"].waiter()(
                    3, prompt_id="p9", options=["a", "b", "c"])),
            daemon=True)
        th.start()
        for _ in range(200):
            if self.ctl["broker"].pending_id == "p9":
                break
            time.sleep(0.005)
        r = self.handle({"cmd": "choice", "prompt_id": "p8", "pick": "a"})
        self.assertEqual(r["error"], "stale_prompt")
        r = self.handle({"cmd": "choice", "prompt_id": "p9", "index": 3})
        self.assertEqual(r, {"ok": True})
        th.join(2)
        self.assertEqual(self.ctl["got"], "c")

    def test_cli_choice_args(self):
        f = self.w._choice_cmd
        self.assertEqual(f(["app:x"]), {"cmd": "choice", "pick": "app:x"})
        self.assertEqual(f(["--index", "2", "--prompt-id", "p1"]),
                         {"cmd": "choice", "pick": "", "index": 2,
                          "prompt_id": "p1"})
        self.assertEqual(f(["--prompt-id=p3", "yes"]),
                         {"cmd": "choice", "pick": "yes",
                          "prompt_id": "p3"})
        self.assertEqual(f([]), {"cmd": "choice", "pick": ""})
        self.assertIsNone(f(["--index", "two"]))


class SentenceSpeakerTest(unittest.TestCase):
    """TTS starts per completed sentence while the answer streams."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.log = self.dir / "tts.log"
        script = self.dir / "fake-tts"
        script.write_text(
            "#!/bin/sh\n"
            f'printf "%s|%s\\n" "$(date +%s.%N)" "$1" >> {self.log}\n'
            f'echo $$ >> {self.dir}/pids\n'
            f'exec sleep "${{FAKE_TTS_SLEEP:-0.05}}"\n')
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        self.cfg = {"voice": {"enabled": "true",
                              "cmd": f"{script} {{text}}"}}
        self.addCleanup(speech.stop)

    def _spoken(self):
        if not self.log.exists():
            return []
        return [l.split("|", 1) for l in self.log.read_text().splitlines()]

    def _wait_spoken(self, n, timeout=2):
        end = time.monotonic() + timeout
        while time.monotonic() < end and len(self._spoken()) < n:
            time.sleep(0.01)
        return self._spoken()

    def test_first_sentence_starts_before_the_stream_ends(self):
        sp = speech.SentenceSpeaker(self.cfg)
        text = "It is half past three. Take an umbrella. Bye"
        sp.feed("It is half")
        self.assertEqual(self._spoken(), [])
        sp.feed("It is half past three.")      # no trailing space yet
        self.assertEqual(self._spoken(), [])
        sp.feed("It is half past three. Take")
        rows = self._wait_spoken(1)
        t_started = time.time()
        self.assertEqual([r[1] for r in rows], ["It is half past three."])
        sp.feed("It is half past three. Take an umbrella. Bye")
        done = threading.Event()
        sp.finish(text, on_done=done.set)
        self.assertTrue(done.wait(3))
        self.assertEqual([r[1] for r in self._spoken()],
                         ["It is half past three.", "Take an umbrella.",
                          "Bye"])
        self.assertTrue(sp.started)
        self.assertLess(float(self._spoken()[0][0]), t_started + 0.01)

    def test_decimals_and_abbreviation_free_split(self):
        sp = speech.SentenceSpeaker(self.cfg)
        sp.feed("It is 3.5 degrees outside and fine. ")
        rows = self._wait_spoken(1)
        self.assertEqual(rows[0][1], "It is 3.5 degrees outside and fine.")
        sp.stop()

    def test_sentences_are_spoken_in_order_not_overlapping(self):
        sp = speech.SentenceSpeaker(self.cfg)
        sp.feed("One. Two. Three. ")
        done = threading.Event()
        sp.finish("One. Two. Three.", on_done=done.set)
        self.assertTrue(done.wait(3))
        self.assertEqual([r[1] for r in self._spoken()],
                         ["One.", "Two.", "Three."])
        ts = [float(r[0]) for r in self._spoken()]
        self.assertEqual(ts, sorted(ts))

    def test_stop_kills_the_speaking_child_and_drops_the_queue(self):
        os.environ["FAKE_TTS_SLEEP"] = "30"
        self.addCleanup(os.environ.pop, "FAKE_TTS_SLEEP", None)
        tok = cancel.CancelToken()
        sp = speech.SentenceSpeaker(self.cfg, token=tok)
        sp.feed("First one. Second one. Third one. ")
        self._wait_spoken(1)
        pids = [int(p) for p in (self.dir / "pids").read_text().split()]
        t = time.monotonic()
        tok.cancel()
        for _ in range(100):
            if not _alive(pids[0]):
                break
            time.sleep(0.005)
        self.assertLess(time.monotonic() - t, 0.4)
        self.assertFalse(_alive(pids[0]))
        time.sleep(0.2)
        self.assertEqual(len(self._spoken()), 1, "queue kept speaking")

    def test_module_stop_also_stops_an_active_speaker(self):
        os.environ["FAKE_TTS_SLEEP"] = "30"
        self.addCleanup(os.environ.pop, "FAKE_TTS_SLEEP", None)
        sp = speech.SentenceSpeaker(self.cfg)
        sp.feed("First one. Second one. ")
        self._wait_spoken(1)
        pid = int((self.dir / "pids").read_text().split()[0])
        speech.stop()
        time.sleep(0.2)
        self.assertFalse(_alive(pid))
        self.assertEqual(len(self._spoken()), 1)

    def test_voice_disabled_speaks_nothing(self):
        cfg = {"voice": {"enabled": "false", "cmd": self.cfg["voice"]["cmd"]}}
        sp = speech.SentenceSpeaker(cfg)
        sp.feed("One. Two. ")
        done = threading.Event()
        sp.finish("One. Two.", on_done=done.set)
        self.assertTrue(done.wait(1))
        self.assertFalse(sp.started)
        self.assertEqual(self._spoken(), [])

    def test_finish_speaks_only_the_unspoken_tail(self):
        sp = speech.SentenceSpeaker(self.cfg)
        sp.feed("Alpha. Beta ")
        self._wait_spoken(1)
        done = threading.Event()
        sp.finish("Alpha. Beta gamma.", on_done=done.set)
        self.assertTrue(done.wait(3))
        self.assertEqual([r[1] for r in self._spoken()],
                         ["Alpha.", "Beta gamma."])


class StreamingTtsThroughAskChatTest(unittest.TestCase):
    """Real brain stream -> sentence speaker: audio starts before the
    stream ends."""

    def test_first_sentence_audio_precedes_the_last_chunk(self):
        d = pathlib.Path(tempfile.mkdtemp())
        log = d / "tts.log"
        script = d / "fake-tts"
        script.write_text(
            f'#!/bin/sh\nprintf "%s|%s\\n" "$(date +%s.%N)" "$1" >> {log}\n'
            "exec sleep 0.05\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        chunks = ["It is ", "half past ", "three. ", "Take ", "an ",
                  "umbrella ", "please."]
        with fakes.FakeBrain({"responses": [{"chunks": chunks,
                                             "chunk_delay_ms": 80}]}) \
                as srv:
            cfg = _brain_cfg(srv.url)
            cfg["voice"] = {"enabled": "true", "cmd": f"{script} {{text}}"}
            cfg["agent"] = {}
            sp = speech.SentenceSpeaker(cfg)
            self.addCleanup(speech.stop)
            reply = pipeline.ask_chat(
                "time?", cfg, on_delta=lambda acc: sp.feed(acc))
            t_end = srv.sent[-1][0]
            wall_end = time.time() - (time.monotonic() - t_end)
            done = threading.Event()
            sp.finish(reply, on_done=done.set)
            self.assertTrue(done.wait(3))
        rows = [l.split("|", 1) for l in log.read_text().splitlines()]
        self.assertEqual([r[1] for r in rows],
                         ["It is half past three.",
                          "Take an umbrella please."])
        self.assertLess(float(rows[0][0]), wall_end,
                        "first sentence was not spoken until the stream "
                        "had ended")


if __name__ == "__main__":
    unittest.main()
