"""A dev/gauntlet task never inherits the previous task's goal or
conversation (an aborted files task used to leak into the next one)."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import act, goals, session  # noqa: E402

DEV = {"dev": {"run_id": "g1"}}


class TestIsolation(unittest.TestCase):
    def setUp(self):
        goals.CURRENT = None
        self.addCleanup(setattr, goals, "CURRENT", None)

    def test_goal_not_joined_in_a_dev_run(self):
        goals.join_or_new("open inner in docs", "org.gnome.Nautilus", DEV)
        g, joined = goals.join_or_new("rename draft.txt to final.txt",
                                      "org.gnome.Nautilus", DEV)
        self.assertFalse(joined)
        self.assertEqual(g["text"], "rename draft.txt to final.txt")

    def test_goal_still_joins_for_the_owner(self):
        goals.join_or_new("open inner in docs", "org.gnome.Nautilus", {})
        _g, joined = goals.join_or_new("rename it", "org.gnome.Nautilus", {})
        self.assertTrue(joined)

    def test_session_tail_empty_in_a_dev_run(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "s.jsonl"
            session.append_turn("open inner", path=p, app="nautilus")
            self.assertEqual(len(session.tail(3, path=p, app="nautilus")), 1)
            self.assertEqual(
                session.tail(3, path=p, app="nautilus", cfg=DEV), [])

    def test_prev_turn_hidden_in_a_dev_run(self):
        # _prev_turn reads the owner's session file; with a dev cfg it
        # must come back empty whatever that file holds
        self.assertEqual(act._prev_turn(None, DEV), "")


if __name__ == "__main__":
    unittest.main()
