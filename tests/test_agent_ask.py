#!/usr/bin/env python3
"""Daemon-level agent ask queue (U7, KTD12): background agents ask by
voice without a turn, never steal a live turn's prompt, fail closed."""
import pathlib
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import agent_ask, cancel, state  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def until(fn, what="condition"):
    for _ in range(400):
        if fn():
            return
        time.sleep(0.005)
    raise AssertionError(f"never: {what}")


class AskBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = state.State(pathlib.Path(self.tmp.name) / "state.json",
                              write_initial=False)
        self.clock = Clock()
        self.broker = cancel.PromptBroker(clock=self.clock)
        self.spoken, self.events, self.answers = [], [], []
        self.busy = threading.Event()
        self.speak_err = None
        self.q = agent_ask.AskQueue(
            self.st, self.broker, self._speak,
            lambda name, **d: self.events.append((name, d)),
            clock=self.clock, busy=self.busy.is_set, poll=0.005)
        self.q.start()
        self.addCleanup(self.q.stop)

    def _speak(self, text):
        if self.speak_err:
            raise self.speak_err
        self.spoken.append(text)

    def submit(self, helper="scout", kind="permission", text="run git push",
               choices=None, secs=120, tag=None):
        tag = tag or text
        return self.q.submit(helper, kind, text, choices,
                             self.clock() + secs,
                             lambda a: self.answers.append((tag, a)))

    def snap(self):
        return self.st.snapshot()


class TestPublishAndAnswer(AskBase):
    def test_idle_ask_publishes_and_choice_answers(self):
        self.submit()
        until(lambda: self.snap()["status"] == "awaiting_choice")
        s = self.snap()
        self.assertEqual(s["source"], "agent:scout")
        self.assertEqual(s["choices"], ["Allow", "No"])
        self.assertTrue(s["prompt_id"])
        out = self.broker.offer(pick="Allow", prompt_id=s["prompt_id"])
        self.assertTrue(out["ok"])
        until(lambda: self.answers)
        self.assertEqual(self.answers, [("run git push", "Allow")])
        until(lambda: self.snap()["prompt_id"] == "")
        s = self.snap()
        self.assertEqual((s["status"], s["source"], s["choices"]),
                         ("idle", "", []))
        self.assertEqual(self.events[-1][0], "task_question")
        self.assertEqual(self.events[-1][1]["outcome"], "answered")

    def test_permission_spoken_template(self):
        self.submit()
        until(lambda: self.spoken)
        self.assertEqual(self.spoken[0],
                         "Scout wants to run git push. Allow or no?")

    def test_question_without_choices_takes_free_text(self):
        self.submit(kind="question", text="Which branch?")
        until(lambda: self.snap()["status"] == "awaiting_choice")
        s = self.snap()
        self.assertEqual(s["choices"], [])
        self.assertIn("Scout asks: Which branch?", self.spoken[0])
        self.broker.offer(pick="release", prompt_id=s["prompt_id"])
        until(lambda: self.answers)
        self.assertEqual(self.answers[0][1], "release")


class TestTurnPriority(AskBase):
    def test_ask_waits_while_a_turn_holds_the_broker(self):
        self.busy.set()
        wait = self.broker.waiter()
        res = {}
        th = threading.Thread(
            target=lambda: res.update(p=wait(5, prompt_id="t1",
                                             options=["a"])),
            daemon=True)
        th.start()
        until(lambda: self.broker.pending_id == "t1")
        self.submit()
        time.sleep(0.1)
        self.assertEqual(self.snap()["source"], "")
        self.broker.offer(pick="a", prompt_id="t1")
        th.join(2)
        self.assertEqual(res["p"], "a")
        self.busy.clear()
        until(lambda: self.snap()["source"] == "agent:scout")

    def test_turn_starting_withdraws_then_ask_returns(self):
        self.submit()
        until(lambda: self.snap()["source"] == "agent:scout")
        first = self.snap()["prompt_id"]
        self.busy.set()
        self.q.withdraw()
        self.assertEqual(self.answers, [])
        self.assertEqual(self.snap()["source"], "")
        # the turn's own prompt now gets the broker
        res = {}
        th = threading.Thread(
            target=lambda: res.update(p=self.broker.waiter()(
                5, prompt_id="t1", options=["a"])), daemon=True)
        th.start()
        until(lambda: self.broker.pending_id == "t1")
        self.broker.offer(pick="a", prompt_id="t1")
        th.join(2)
        self.assertEqual(res["p"], "a")
        self.st.transition("done", choices=[], prompt_id="")  # turn ends
        self.busy.clear()
        until(lambda: self.snap()["source"] == "agent:scout")
        s = self.snap()
        self.assertNotEqual(s["prompt_id"], first)
        self.assertEqual(self.spoken[0], self.spoken[-1])
        self.assertEqual(len(self.spoken), 2)
        self.assertEqual(self.answers, [])


class TestOrderAndDeadline(AskBase):
    def test_same_helper_asks_are_offered_one_after_the_other(self):
        self.submit(text="run ls", tag="one")
        self.submit(text="run rm", tag="two")
        until(lambda: self.snap()["source"] == "agent:scout")
        self.assertEqual(len(self.spoken), 1)
        self.assertIn("run ls", self.spoken[0])
        self.broker.offer(pick="Allow",
                          prompt_id=self.snap()["prompt_id"])
        until(lambda: len(self.spoken) == 2)
        self.assertIn("run rm", self.spoken[1])
        self.assertEqual(self.answers, [("one", "Allow")])
        until(lambda: self.snap()["prompt_id"] and self.broker.pending_id)
        self.broker.offer(pick="No", prompt_id=self.snap()["prompt_id"])
        until(lambda: len(self.answers) == 2)
        self.assertEqual(self.answers[1], ("two", "No"))

    def test_deadline_rejects_permission(self):
        self.submit(secs=120)
        until(lambda: self.broker.pending_id)
        self.clock.t += 121
        until(lambda: self.answers)
        self.assertEqual(self.answers[0][1], agent_ask.REJECT)
        self.assertEqual(self.events[-1][0], "task_question")
        self.assertEqual(self.events[-1][1]["outcome"], "timed_out")
        until(lambda: self.snap()["source"] == "")

    def test_deadline_gives_question_no_answer(self):
        self.submit(kind="question", text="Which?", choices=["a", "b"])
        until(lambda: self.broker.pending_id)
        self.clock.t += 121
        until(lambda: self.answers)
        self.assertIsNone(self.answers[0][1])
        self.assertEqual(self.events[-1][1]["outcome"], "timed_out")


class TestSpeechFailure(AskBase):
    def test_tts_failure_leaves_ask_answerable_and_expiring(self):
        self.speak_err = RuntimeError("tts down")
        self.submit()
        until(lambda: self.broker.pending_id)
        self.assertEqual(self.snap()["source"], "agent:scout")
        self.clock.t += 121
        until(lambda: self.answers)
        self.assertEqual(self.answers[0][1], agent_ask.REJECT)


if __name__ == "__main__":
    unittest.main()
