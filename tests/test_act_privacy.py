"""Plain replies do not become persistent action trajectories."""
import unittest
from unittest import mock

from wisp import act


class ActionTrajectoryBoundary(unittest.TestCase):
    def test_empty_answer_does_not_queue_a_transcript_write(self):
        with mock.patch.object(act.bgwriter, "submit") as submit, \
                mock.patch("wisp.trajectories.record") as record:
            act._record_traj("private question", None, [], "plain reply", {})
        submit.assert_not_called()
        record.assert_not_called()

    def test_real_action_keeps_its_copied_trajectory(self):
        steps = [{"tool": "click", "arg": "save", "result": "CLICKED"}]
        with mock.patch.object(act.bgwriter, "submit") as submit, \
                mock.patch.object(act, "_app", return_value="fixture-browser"), \
                mock.patch.object(act, "_surface", return_value="desktop"), \
                mock.patch("wisp.trajectories.record") as record:
            act._record_traj("save document", None, steps, "saved", {})
            submit.assert_called_once()
            steps[0]["result"] = "later mutation"
            submit.call_args.args[0]()
        record.assert_called_once_with(
            "save document", "fixture-browser",
            [{"tool": "click", "arg": "save", "result": "CLICKED"}],
            "saved", surface="desktop", pack=None)
