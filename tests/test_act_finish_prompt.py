"""The act prompt tells the model to submit typed text and check the result.

The 2026-11-02 gauntlet reruns found the biggest failure class was the
model typing into a terminal or address bar and never pressing Enter, or
reporting success without looking (docs/research/2026-11-02-gauntlet-reruns.md).
"""
import unittest

from wisp import act


class FinishRulesTest(unittest.TestCase):
    def test_enter_after_single_line_typing_only(self):
        self.assertIn("Typing is not submitting", act.SYSTEM)
        self.assertIn("single-line field", act.SYSTEM)
        self.assertIn("multi-line field", act.SYSTEM)
        self.assertIn("press enter only when the task is to send", act.SYSTEM)

    def test_verify_before_success_with_one_screenshot_cap(self):
        self.assertIn("Never report success from the typing step alone",
                      act.SYSTEM)
        self.assertIn("at most one extra screenshot per turn", act.SYSTEM)

    def test_open_by_select_then_enter_since_double_click_is_blocked(self):
        from wisp.tools import system
        self.assertIn("double_click", system.BLOCKED_INPUT)
        self.assertIn("click it once to select it, then press enter",
                      act.SYSTEM)


if __name__ == "__main__":
    unittest.main()
