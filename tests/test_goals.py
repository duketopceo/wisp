"""Goal memory: continuations join the open goal; new topics start
fresh; TTL expiry closes it."""
import time
import unittest

from wisp import goals


class GoalsTest(unittest.TestCase):
    def setUp(self):
        goals.CURRENT = None
        self.cfg = {"agent": {"goal_ttl_s": "600"}}

    def test_first_utterance_opens_goal(self):
        g, joined = goals.join_or_new("check robinhood", "firefox",
                                      self.cfg)
        self.assertFalse(joined)
        self.assertEqual(g["status"], "open")
        self.assertEqual(g["app"], "firefox")

    def test_same_app_joins(self):
        goals.join_or_new("check robinhood", "firefox", self.cfg)
        g, joined = goals.join_or_new("open a new tab", "firefox",
                                      self.cfg)
        self.assertTrue(joined)
        self.assertIn("then: open a new tab", g["text"])

    def test_related_topic_joins_across_apps(self):
        goals.join_or_new("get to GDX on robinhood", "firefox", self.cfg)
        _, joined = goals.join_or_new("click on GDX", "alacritty",
                                      self.cfg)
        self.assertTrue(joined)

    def test_unrelated_new_app_starts_fresh(self):
        goals.join_or_new("check robinhood", "firefox", self.cfg)
        g, joined = goals.join_or_new("launch discord", "foot", self.cfg)
        self.assertFalse(joined)
        self.assertEqual(g["text"], "launch discord")

    def test_ttl_expiry_starts_fresh(self):
        goals.join_or_new("check robinhood", "firefox",
                          {"agent": {"goal_ttl_s": "1"}})
        goals.CURRENT["ts"] = time.time() - 5
        _, joined = goals.join_or_new("open a new tab", "firefox",
                                      {"agent": {"goal_ttl_s": "1"}})
        self.assertFalse(joined)

    def test_steps_recorded_and_capped(self):
        goals.join_or_new("task", "firefox", self.cfg)
        goals.record_steps([{"tool": f"t{i}"} for i in range(20)])
        self.assertEqual(len(goals.CURRENT["steps"]), 12)

    def test_close_clears_current(self):
        goals.join_or_new("task", "firefox", self.cfg)
        goals.close("done")
        self.assertIsNone(goals.CURRENT)

    def test_context_text_empty_when_closed(self):
        self.assertEqual(goals.context_text(), "")
        goals.join_or_new("task", "firefox", self.cfg)
        self.assertIn("[goal] task", goals.context_text())


if __name__ == "__main__":
    unittest.main()
