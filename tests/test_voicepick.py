#!/usr/bin/env python3
"""Voice answers to pending prompts — wisp/voicepick.py plus the wispd
mini-capture wiring.

Fakes only: transcribe/record are mocked, no audio, no live daemon, no
paid calls.
"""
import importlib.machinery
import importlib.util
import pathlib
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import cancel, voicepick  # noqa: E402


class MapPickTest(unittest.TestCase):
    CONFIRM = ["close Slack — yes", "no"]
    APPS = ["app:firefox", "app:slack", "app:godot"]

    def pick(self, text, options=None):
        return voicepick.map_pick(
            text, self.CONFIRM if options is None else options)

    # -- binary confirm cards --------------------------------------
    def test_affirmations_pick_the_yes_side(self):
        for u in ("yes", "yeah", "yep", "do it", "go ahead", "allow",
                  "confirm", "sure, go for it", "okay"):
            self.assertEqual(self.pick(u), 0, u)

    def test_denials_pick_the_no_side(self):
        for u in ("no", "nope", "don't", "cancel", "deny",
                  "do not do it", "never mind"):
            self.assertEqual(self.pick(u), 1, u)

    def test_negation_beats_an_embedded_affirmation(self):
        self.assertEqual(self.pick("don't go ahead"), 1)

    def test_affirm_against_nonconfirm_falls_through(self):
        # "yes" on a 3-way card is not a confirmation answer
        self.assertIsNone(self.pick("yes", self.APPS))

    # -- ordinals and digits ---------------------------------------
    def test_ordinals_and_digits(self):
        self.assertEqual(self.pick("the second one", self.APPS), 1)
        self.assertEqual(self.pick("first", self.APPS), 0)
        self.assertEqual(self.pick("three", self.APPS), 2)
        self.assertEqual(self.pick("2", self.APPS), 1)

    def test_out_of_range_ordinal_maps_nothing(self):
        self.assertIsNone(self.pick("the fifth one", self.APPS))
        self.assertIsNone(self.pick("0", self.APPS))

    def test_ordinal_works_on_confirm_cards_too(self):
        self.assertEqual(self.pick("the first option"), 0)

    # -- label overlap ----------------------------------------------
    def test_option_text_overlap(self):
        self.assertEqual(self.pick("open firefox", self.APPS), 0)
        self.assertEqual(self.pick("godot please", self.APPS), 2)
        self.assertEqual(self.pick("use app:slack", self.APPS), 1)

    def test_overlap_ignores_short_words(self):
        # 'it', 'go', 'no' must never bind through overlap
        self.assertIsNone(self.pick("go for it", self.APPS))
        self.assertIsNone(self.pick("no", self.APPS))

    def test_overlap_case_and_punctuation(self):
        self.assertEqual(self.pick("FIREFOX.", self.APPS), 0)

    def test_ambiguous_and_empty_map_nothing(self):
        self.assertIsNone(self.pick("", self.APPS))
        self.assertIsNone(self.pick("hmm", self.APPS))
        self.assertIsNone(self.pick("yes", []))
        self.assertIsNone(voicepick.map_pick("yes", None))

    # -- is_stop -----------------------------------------------------
    def test_is_stop(self):
        for u in ("stop", "cancel", "never mind", "wait", "abort",
                  "no wait hold on"):
            self.assertTrue(voicepick.is_stop(u), u)
        for u in ("", "keep going", "the second one"):
            self.assertFalse(voicepick.is_stop(u), u)


def _load_wispd():
    loader = importlib.machinery.SourceFileLoader(
        "wispd_va", str(ROOT / "wispd"))
    spec = importlib.util.spec_from_loader("wispd_va", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class VoiceAnswerWiringTest(unittest.TestCase):
    """A press while a turn is parked records a mini-capture and offers
    the mapped pick to the live broker — never a new turn."""

    def setUp(self):
        self.w = _load_wispd()
        self.ctl = {"stop": threading.Event(), "busy": threading.Event(),
                    "interrupt": threading.Event(),
                    "choice_event": threading.Event(), "choice_pick": "",
                    "rec": None, "rec_lock": threading.Lock(),
                    "broker": cancel.PromptBroker(),
                    "token": cancel.CancelToken()}
        self.st = mock.Mock()
        self.st.current_turn.return_value = "t1"
        self.handle = self.w._handler(self.st, {}, self.ctl)

    def _park(self, options):
        """Open a prompt like a waiting turn does; return the got-box."""
        box = {}
        th = threading.Thread(
            target=lambda: box.__setitem__(
                "pick", self.ctl["broker"].waiter()(
                    30, prompt_id="p42", options=options)),
            daemon=True)
        th.start()
        for _ in range(400):
            if self.ctl["broker"].pending_id == "p42":
                return box, th
            time.sleep(0.005)
        self.fail("prompt never went pending")

    def _mini_turn(self, text="yes"):
        """Drive the press→release cycle as if the user spoke `text`."""
        self.ctl["busy"].set()
        with mock.patch.object(self.w.pipeline, "record_start",
                               return_value={"t0": time.monotonic() - 1,
                                             "proc": None,
                                             "sampler_stop":
                                             threading.Event()}) as rs, \
             mock.patch.object(self.w.pipeline, "record_stop",
                               return_value=pathlib.Path("/tmp/x.wav")), \
             mock.patch.object(self.w.pipeline, "transcribe",
                               return_value=text):
            press = self.handle({"cmd": "listen"})
            rel = self.handle({"cmd": "listen"})
        return press, rel, rs

    def test_press_while_awaiting_choice_starts_mini_not_busy(self):
        box, th = self._park(["deploy — yes", "no"])
        press, rel, _ = self._mini_turn("yes do it")
        self.assertTrue(press["recording"])
        self.assertEqual(press["mini"], "choice")
        self.assertEqual(rel, {"ok": True})
        th.join(2)
        self.assertEqual(box["pick"], "deploy — yes")

    def test_spoken_no_resolves_the_prompt(self):
        box, th = self._park(["deploy — yes", "no"])
        _, rel, _ = self._mini_turn("nope")
        self.assertEqual(rel, {"ok": True})
        th.join(2)
        self.assertEqual(box["pick"], "no")

    def test_ordinal_picks_the_nth_option(self):
        box, th = self._park(["app:a", "app:b", "app:c"])
        _, rel, _ = self._mini_turn("the third one")
        self.assertEqual(rel, {"ok": True})
        th.join(2)
        self.assertEqual(box["pick"], "app:c")

    def test_unmapped_speech_leaves_the_prompt_pending(self):
        _, th = self._park(["deploy — yes", "no"])
        _, rel, _ = self._mini_turn("um what was the question")
        self.assertTrue(rel["ok"])
        self.assertFalse(rel["mapped"])
        self.assertEqual(self.ctl["broker"].pending_id, "p42")
        # the waiter is still parked — an IPC click still resolves it
        self.assertEqual(
            self.ctl["broker"].offer(index=1, prompt_id="p42"),
            {"ok": True})
        th.join(2)

    def test_prompt_timing_out_during_capture_is_not_an_error(self):
        _, th = self._park(["deploy — yes", "no"])
        # the turn side of the broker resolves first (its own timeout or
        # a UI click); by release there is nothing pending
        self.ctl["broker"].offer(index=1, prompt_id="p42")
        th.join(2)
        _, rel, _ = self._mini_turn("yes")
        self.assertTrue(rel["ok"])
        self.assertFalse(rel["mapped"])

    def test_mini_release_does_not_start_a_normal_turn(self):
        self._park(["deploy — yes", "no"])
        self.ctl["busy"].set()
        with mock.patch.object(self.w.threading, "Thread") as t, \
             mock.patch.object(self.w.pipeline, "record_start",
                               return_value={"t0": time.monotonic() - 1,
                                             "proc": None,
                                             "sampler_stop":
                                             threading.Event()}), \
             mock.patch.object(self.w.pipeline, "record_stop",
                               return_value=pathlib.Path("/tmp/x.wav")), \
             mock.patch.object(self.w.pipeline, "transcribe",
                               return_value="yes"):
            self.handle({"cmd": "listen"})
            self.handle({"cmd": "listen"})
        # _run_listen must never be spawned for a mini-capture
        for c in t.call_args_list:
            self.assertIsNot(c.kwargs.get("target"), self.w._run_listen)

    def test_spoken_stop_cancels_the_running_turn(self):
        self.ctl["busy"].set()  # a turn is running, no prompt pending
        press, rel, _ = self._mini_turn("stop stop stop")
        self.assertEqual(press["mini"], "stop")
        self.assertEqual(rel["result"], "interrupted")
        self.assertTrue(self.ctl["interrupt"].is_set())
        self.assertTrue(self.ctl["token"].cancelled)

    def test_non_stop_speech_does_not_interrupt(self):
        self.ctl["busy"].set()
        _, rel, _ = self._mini_turn("also make it blue")
        self.assertFalse(rel.get("mapped", True))
        self.assertFalse(self.ctl["interrupt"].is_set())
        self.assertFalse(self.ctl["token"].cancelled)

    def test_idle_press_is_a_normal_recording_not_mini(self):
        with mock.patch.object(self.w.pipeline, "record_start",
                               return_value={"t0": time.monotonic()}) as rs:
            self.st.begin_turn.return_value = "t9"
            self.st.turn.return_value = mock.Mock()
            self.w.speech = mock.Mock()
            self.w._drop_speculation = mock.Mock()
            with mock.patch.object(self.w.pipeline,
                                   "speculative_context",
                                   return_value=mock.Mock()):
                r = self.handle({"cmd": "listen"})
        self.assertTrue(r["recording"])
        self.assertNotIn("mini", r)
        self.assertNotIn("mini", self.ctl)
        rs.assert_called_once()

    def test_stt_failure_is_a_clean_error(self):
        self._park(["deploy — yes", "no"])
        with mock.patch.object(self.w.pipeline, "transcribe",
                               side_effect=RuntimeError("no stt")), \
             mock.patch.object(self.w.pipeline, "record_stop",
                               return_value=pathlib.Path("/tmp/x.wav")):
            self.ctl["mini"] = "choice"
            self.ctl["rec"] = {"t0": time.monotonic() - 1, "proc": None,
                               "sampler_stop": threading.Event()}
            r = self.handle({"cmd": "listen"})
        self.assertEqual(r["error"], "stt_down")
        self.assertIsNone(self.ctl["rec"])
        self.assertNotIn("mini", self.ctl)


class ContinuityTest(unittest.TestCase):
    """U4: a question wisp logged last turn rides into this turn's
    router context, so 'yes do it' resolves against 'wisp: asked:'
    instead of starting blind."""

    def test_asked_question_reaches_jev_context(self):
        from wisp import memory as mem, pipeline, session as sess
        from wisp import state as state_mod, trace
        import tempfile
        d = pathlib.Path(tempfile.mkdtemp())
        tf = d / "trace.jsonl"
        st = state_mod.StateBus(state_file=d / "state.json")
        captured = {}
        # session.tail's default path binds config.SESSION_FILE at
        # def-time — feed the turns in directly instead
        turns = [{"transcript": "check the deployment",
                  "result": "ASK_USER which account?"},
                 {"transcript": "should I fix the connection first",
                  "result": "ASK_USER: fix the connection first?"}]

        def jev(text, model, questions, context="", cfg=None):
            captured["context"] = context
            return {"answers": {"route": {"choice": "answer"},
                                "confidence": {"score": 0.9},
                                "app": {"choice": ""}}}
        cfg = {"audio": {"seconds": "0"}, "agent": {}}
        with mock.patch.object(trace, "TRACE_FILE", tf), \
             mock.patch.object(sess, "tail", return_value=turns), \
             mock.patch.object(pipeline, "transcribe",
                               return_value="yes do it"), \
             mock.patch.object(pipeline, "capture_screen",
                               return_value=None), \
             mock.patch.object(pipeline, "ask_jev", side_effect=jev), \
             mock.patch.object(pipeline, "execute",
                               return_value="ANSWERED"), \
             mock.patch.object(pipeline, "ask_chat",
                               return_value="deploying"), \
             mock.patch.object(pipeline, "build_questions",
                               return_value={}), \
             mock.patch.object(pipeline, "active_window",
                               return_value={}), \
             mock.patch.object(pipeline, "notify"), \
             mock.patch.object(pipeline.speech, "speak",
                               return_value=None), \
             mock.patch.object(mem, "context_block", return_value=""), \
             mock.patch.object(pipeline, "log_decision"):
            trace.reset_cache()
            rc = pipeline.run_listen(cfg, st, wav=d / "x.wav")
            trace.reset_cache()
        self.assertEqual(rc, 0)
        # both ASK_USER spellings render as conversation, not jargon
        self.assertIn("wisp: asked: which account?",
                      captured["context"])
        self.assertIn("wisp: asked: fix the connection first?",
                      captured["context"])
        self.assertNotIn("ASK_USER", captured["context"])


if __name__ == "__main__":
    unittest.main()
