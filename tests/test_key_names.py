"""The key tool knows the function keys, Delete and Insert on both paths.

The ydotool path sends evdev codes; the isolated path sends wtype keysym
names. Gauntlet runs failed files-rename with "unknown key 'f2'".
"""
import types
import unittest
from unittest import mock

from wisp import cua_safety
from wisp.tools import system


def _ok(*_a, **_k):
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


class KeyNamesTest(unittest.TestCase):
    def press(self, name):
        with mock.patch.object(system._cancel, "run", side_effect=_ok) as run, \
                mock.patch.object(system._vp, "is_isolated", return_value=False):
            out = system.key(name, {})
        return out, run

    def test_function_keys_send_their_evdev_codes(self):
        expect = {"f1": 59, "f2": 60, "f10": 68, "f11": 87, "f12": 88,
                  "delete": 111, "del": 111, "insert": 110}
        for name, code in expect.items():
            out, run = self.press(name)
            self.assertEqual(out, "KEY", name)
            argv = run.call_args[0][0]
            self.assertEqual(argv[-2:], [f"{code}:1", f"{code}:0"], name)

    def test_upper_case_and_chords_work(self):
        out, run = self.press("F2")
        self.assertEqual(run.call_args[0][0][-2:], ["60:1", "60:0"])
        out, run = self.press("shift+f10")
        self.assertEqual(out, "KEY")

    def test_unknown_keys_still_skip(self):
        out, run = self.press("f13")
        self.assertEqual(out, "SKIP (unknown key 'f13')")
        run.assert_not_called()

    def test_wtype_names_for_the_isolated_session(self):
        self.assertEqual(system._wtype_argv("f2"), ["wtype", "-k", "F2"])
        self.assertEqual(system._wtype_argv("f12"), ["wtype", "-k", "F12"])
        self.assertEqual(system._wtype_argv("delete"), ["wtype", "-k", "Delete"])
        self.assertEqual(system._wtype_argv("ctrl+f5"),
                         ["wtype", "-M", "ctrl", "-k", "F5", "-m", "ctrl"])

    def test_audit_logs_function_keys_by_name(self):
        for name in ("f2", "f12", "insert", "delete"):
            self.assertIn(name, cua_safety._NAMED_KEYS)


if __name__ == "__main__":
    unittest.main()
