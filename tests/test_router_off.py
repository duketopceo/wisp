"""An off-router request cannot silently fall through to the act loop."""
import unittest
from unittest import mock

from wisp import cancel, stage_execute


class RouterOffChoiceTest(unittest.TestCase):
    def dispatch(self, ask=None, cfg=None):
        answers = {"route": {"choice": "clarify"}}
        result = stage_execute.execute(
            answers, cfg or {}, detail="do the task", ask=ask,
            user_request="do the task")
        return result, answers

    def test_missing_choice_channel_cannot_execute(self):
        with mock.patch("wisp.act.run_act_loop") as act, \
                mock.patch("wisp.tools.run") as tool:
            result, _ = self.dispatch()
        self.assertTrue(result.startswith("SKIPPED"))
        act.assert_not_called()
        tool.assert_not_called()

    def test_cancel_timeout_and_unknown_answers_cannot_execute(self):
        for pick in (None, "", "Cancel", "act", "untrusted choice"):
            with self.subTest(pick=pick), \
                    mock.patch("wisp.act.run_act_loop") as act, \
                    mock.patch("wisp.tools.run") as tool:
                result, _ = self.dispatch(mock.Mock(return_value=pick))
                self.assertTrue(result.startswith("SKIPPED"))
                act.assert_not_called()
                tool.assert_not_called()

    def test_only_explicit_act_selection_enters_act(self):
        ask = mock.Mock(return_value="Act")
        with mock.patch("wisp.act.run_act_loop", return_value="ACTED") as act:
            result, answers = self.dispatch(ask)
        self.assertEqual(result, "ACTED")
        self.assertEqual(answers["route"]["choice"], "act")
        self.assertEqual(ask.call_args.args[1], ["Explain", "Act", "Dictate", "Cancel"])
        self.assertEqual(act.call_args.kwargs["user_request"], "do the task")

    def test_explain_selection_updates_route_without_executing(self):
        with mock.patch("wisp.act.run_act_loop") as act, \
                mock.patch("wisp.tools.run") as tool:
            result, answers = self.dispatch(mock.Mock(return_value="Explain"))
        self.assertEqual(result, "ANSWERED")
        self.assertEqual(answers["route"]["choice"], "answer")
        act.assert_not_called()
        tool.assert_not_called()

    def test_dictation_requires_its_own_selection(self):
        with mock.patch("wisp.act.run_act_loop") as act, \
                mock.patch("wisp.dictate.run", return_value="DICTATED") as dictate:
            result, answers = self.dispatch(mock.Mock(return_value="Dictate"))
        self.assertEqual(result, "DICTATED")
        self.assertEqual(answers["route"]["choice"], "dictation")
        self.assertEqual(dictate.call_args.args[0], "do the task")
        act.assert_not_called()

    def test_cancelled_prompt_does_not_enter_act(self):
        with mock.patch("wisp.act.run_act_loop") as act:
            with self.assertRaises(cancel.Cancelled):
                self.dispatch(mock.Mock(side_effect=cancel.Cancelled))
        act.assert_not_called()

    def test_unattended_dev_run_never_prompts_or_acts(self):
        ask = mock.Mock(return_value="Act")
        with mock.patch("wisp.act.run_act_loop") as act:
            result, _ = self.dispatch(ask, {"dev": {"run_id": "synthetic"}})
        self.assertTrue(result.startswith("SKIPPED"))
        ask.assert_not_called()
        act.assert_not_called()
