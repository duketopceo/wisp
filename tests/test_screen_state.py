import sys, pathlib, unittest
from unittest import mock
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import screen_state as ss  # noqa: E402
from wisp.tools import system  # noqa: E402


def fake(locked="no", pgrep="", monitors='[{"dpmsStatus": true}]'):
    def run(cmd, timeout=1.5):
        if cmd[0] == "loginctl":
            return locked + "\n"
        if cmd[0] == "pgrep":
            return pgrep
        if cmd[0] == "hyprctl":
            return monitors
        return None
    return run


class Detect(unittest.TestCase):
    def setUp(self):
        ss.clear()

    def test_available(self):
        self.assertEqual(ss.unavailable(run=fake()), "")

    def test_logind_locked(self):
        self.assertEqual(ss.unavailable(run=fake(locked="yes")),
                         "session locked")

    def test_locker_process(self):
        self.assertEqual(ss.unavailable(run=fake(pgrep="123\n")),
                         "session locked")

    def test_all_outputs_off(self):
        self.assertIn("no live output", ss.unavailable(
            run=fake(monitors='[{"dpmsStatus": false}]')))

    def test_probes_fail_open(self):
        self.assertEqual(ss.unavailable(run=lambda *a, **k: None), "")
        self.assertEqual(ss.unavailable(run=fake(monitors="not json")), "")

    def test_dom_page_never_blocked(self):
        self.assertEqual(ss.unavailable({"screen": {"dom_page": "x"}},
                                        run=fake(locked="yes")), "")

    def test_report_once_until_cleared(self):
        self.assertTrue(ss.report_once("session locked"))
        self.assertFalse(ss.report_once("session locked"))
        ss.clear_reported()
        self.assertTrue(ss.report_once("session locked"))


class Tool(unittest.TestCase):
    def setUp(self):
        ss.clear()

    def test_locked_session_skips_cleanly_and_logs_once(self):
        logs = []
        with mock.patch.object(ss, "unavailable",
                               return_value="session locked"), \
                mock.patch.object(system, "_log_screen", logs.append), \
                mock.patch.object(system._cancel, "run") as grim:
            outs = [system.screenshot("", {}) for _ in range(120)]
        grim.assert_not_called()
        self.assertTrue(all(ss.is_unavailable(o) for o in outs))
        self.assertIn("session locked", outs[0])
        self.assertEqual(len(logs), 1)


if __name__ == "__main__":
    unittest.main()
