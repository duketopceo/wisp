"""Suggestion miner tests, runnable as their own discover pattern.

The miner cases live in test_sense.py; this module re-exports them so
`-p test_suggest.py` exercises suggest.mine/resolve_pick alongside the
H6 etiquette policy smoke checks below.
"""
import unittest

import test_sense
from wisp import suggest_policy


class TestSuggest(test_sense.TestSuggest):
    pass


class TestEtiquetteSmoke(unittest.TestCase):
    def test_policy_allows_midday_idle(self):
        r = suggest_policy.evaluate_suggestion_etiquette(
            local_hour=10, current_day="2026-10-16")
        self.assertTrue(r["allow"])

    def test_policy_holds_in_call(self):
        r = suggest_policy.evaluate_suggestion_etiquette(
            local_hour=10, in_call=True, current_day="2026-10-16")
        self.assertEqual((r["action"], r["reason"]), ("hold", "in_call"))


if __name__ == "__main__":
    unittest.main()
