#!/usr/bin/env python3
"""Confirm card backend (W25, Ember U15): prompt ids, timeout, deny result.

The confirm prompt rides the same prompt-id channel as a clarify prompt
(#66): the daemon publishes `confirm` next to `choices`/`prompt_id`, a
reply with another id is ignored, and no reply inside `confirm_timeout`
seconds resolves as deny. The timeout is daemon-side (the waiter's own
deadline on an injectable clock); the shell adds no timer for it.
"""
import pathlib
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import act, cancel, confirm, copy as wcopy, state  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class ConfirmBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = state.State(pathlib.Path(self.tmp.name) / "state.json",
                              write_initial=False)
        self.clock = Clock()
        self.broker = cancel.PromptBroker(clock=self.clock)
        self.token = cancel.CancelToken()
        self.ask = confirm.make(self.st, self.broker.waiter(self.token),
                                self.token, "t1", {}, clock=self.clock)
        self.out = {}

    def run_confirm(self, prompt="run click: save?"):
        def go():
            try:
                self.out["ok"] = self.ask(prompt)
            except cancel.Cancelled:
                self.out["cancelled"] = True
        th = threading.Thread(target=go, daemon=True)
        th.start()
        self.addCleanup(th.join, 2)
        for _ in range(400):
            if self.broker.pending_id:
                return th
            time.sleep(0.005)
        self.fail("confirm never became pending")

    def wait_done(self, th):
        th.join(3)
        self.assertFalse(th.is_alive(), "confirm did not finish")


class TestConfirmPublish(ConfirmBase):
    def test_confirm_absent_by_default(self):
        self.assertIsNone(self.st.snapshot()["confirm"])

    def test_pending_confirm_publishes_card_with_prompt_id(self):
        th = self.run_confirm()
        snap = self.st.snapshot()
        pid = self.broker.pending_id
        self.assertEqual(snap["status"], "awaiting_choice")
        self.assertEqual(snap["prompt_id"], pid)
        self.assertEqual(snap["confirm"]["prompt_id"], pid)
        self.assertEqual(snap["confirm"]["prompt"], "run click: save?")
        self.assertEqual(snap["confirm"]["timeout_s"], 120)
        self.assertEqual(snap["choices"], ["run click: save? — yes", "no"])
        self.broker.offer(pick="no", prompt_id=pid)
        self.wait_done(th)

    def test_answer_clears_the_card(self):
        th = self.run_confirm()
        pid = self.broker.pending_id
        self.assertTrue(self.broker.offer(index=1, prompt_id=pid)["ok"])
        self.wait_done(th)
        self.assertTrue(self.out["ok"])
        self.assertEqual(self.ask.last, "yes")
        snap = self.st.snapshot()
        self.assertIsNone(snap["confirm"])
        self.assertEqual((snap["status"], snap["choices"], snap["prompt_id"]),
                         ("acting", [], ""))

    def test_no_is_deny(self):
        th = self.run_confirm()
        self.broker.offer(pick="no", prompt_id=self.broker.pending_id)
        self.wait_done(th)
        self.assertFalse(self.out["ok"])
        self.assertEqual(self.ask.last, "no")


class TestPromptIdMismatch(ConfirmBase):
    def test_reply_with_another_prompt_id_is_ignored(self):
        th = self.run_confirm()
        pid = self.broker.pending_id
        r = self.broker.offer(pick="no", prompt_id="p-old")
        self.assertEqual(r, {"ok": False, "error": "stale_prompt"})
        self.assertTrue(th.is_alive())
        self.assertEqual(self.st.snapshot()["confirm"]["prompt_id"], pid)
        # the right id still answers it
        self.assertTrue(self.broker.offer(index=1, prompt_id=pid)["ok"])
        self.wait_done(th)
        self.assertTrue(self.out["ok"])

    def test_reply_after_the_confirm_ended_is_stale(self):
        th = self.run_confirm()
        pid = self.broker.pending_id
        self.broker.offer(pick="no", prompt_id=pid)
        self.wait_done(th)
        self.assertEqual(self.broker.offer(pick="no", prompt_id=pid),
                         {"ok": False, "error": "stale_prompt"})

    def test_a_pick_that_was_not_offered_is_rejected(self):
        th = self.run_confirm()
        pid = self.broker.pending_id
        r = self.broker.offer(pick="yes please", prompt_id=pid)
        self.assertEqual(r["error"], "not_offered")
        self.assertTrue(th.is_alive())
        self.broker.offer(pick="no", prompt_id=pid)
        self.wait_done(th)


class TestConfirmTimeout(ConfirmBase):
    def test_timeout_resolves_as_deny_and_clears_the_card(self):
        th = self.run_confirm()
        self.clock.t += 119.0
        time.sleep(0.08)
        self.assertTrue(th.is_alive(), "denied before the deadline")
        self.assertIsNotNone(self.st.snapshot()["confirm"])
        self.clock.t += 2.0
        self.wait_done(th)
        self.assertFalse(self.out["ok"])
        self.assertEqual(self.ask.last, "timeout")
        snap = self.st.snapshot()
        self.assertIsNone(snap["confirm"])
        self.assertEqual((snap["status"], snap["prompt_id"]), ("acting", ""))

    def test_late_reply_after_timeout_is_stale(self):
        th = self.run_confirm()
        pid = self.broker.pending_id
        self.clock.t += 500
        self.wait_done(th)
        self.assertEqual(self.broker.offer(pick="no", prompt_id=pid)["error"],
                         "stale_prompt")

    def test_timeout_is_configurable_and_clamped(self):
        t = confirm.timeout_s
        self.assertEqual(t({}), 120)
        self.assertEqual(t({"agent": {"confirm_timeout": "45"}}), 45)
        self.assertEqual(t({"agent": {"confirm_timeout": "1"}}), 5)
        self.assertEqual(t({"agent": {"confirm_timeout": "99999"}}), 600)
        self.assertEqual(t({"agent": {"confirm_timeout": "soon"}}), 120)

    def test_published_timeout_follows_config(self):
        ask = confirm.make(self.st, self.broker.waiter(self.token),
                           self.token, "t1",
                           {"agent": {"confirm_timeout": "30"}},
                           clock=self.clock)
        th = threading.Thread(target=lambda: ask("p?"), daemon=True)
        th.start()
        for _ in range(400):
            if self.broker.pending_id:
                break
            time.sleep(0.005)
        self.assertEqual(self.st.snapshot()["confirm"]["timeout_s"], 30)
        self.clock.t += 31
        th.join(3)
        self.assertFalse(th.is_alive())

    def test_stop_during_confirm_cancels(self):
        th = self.run_confirm()
        self.token.cancel()
        th.join(3)
        self.assertFalse(th.is_alive())
        self.assertTrue(self.out.get("cancelled"))  # token.check() raised


class TestDenyResult(unittest.TestCase):
    def gate(self, last):
        def ask(prompt):
            return False
        ask.last = last
        return act._gate("close", "w1", {}, ask, state=None)

    def test_timeout_publishes_its_own_result(self):
        r = self.gate("timeout")
        self.assertEqual(r, "SKIPPED (close confirmation timed out)")
        self.assertEqual(wcopy.translate_result(r)["text"],
                         "skipped, no answer")

    def test_a_no_still_reads_you_said_no(self):
        r = self.gate("no")
        self.assertEqual(r, "SKIPPED (close declined by user)")
        self.assertEqual(wcopy.translate_result(r)["text"],
                         "skipped, you said no")


if __name__ == "__main__":
    unittest.main()
