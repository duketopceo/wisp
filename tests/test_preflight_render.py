"""preflight.render: the install/update report."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import preflight  # noqa: E402
from wisp.cli import output  # noqa: E402

ROWS = [
    {"id": "home", "level": "ok", "detail": "user directory available",
     "fix": ""},
    {"id": "python", "level": "ok", "detail": "3.13.5", "fix": ""},
    {"id": "architecture", "level": "block", "detail": "unsupported",
     "fix": "Use Linux x86_64/aarch64."},
    {"id": "hyprctl", "level": "degraded", "detail": "not found; needed for "
     "the push-to-talk bind and pointer",
     "fix": "Install separately if you need this capability."},
    {"id": "grim", "level": "degraded", "detail": "not found; needed for "
     "screen capture",
     "fix": "Install separately if you need this capability."},
    {"id": "wtype", "level": "degraded", "detail": "not found; needed for "
     "typing into other windows",
     "fix": "Install separately if you need this capability."},
    {"id": "desktop session", "level": "degraded",
     "detail": "missing WAYLAND_DISPLAY; live desktop access not probed",
     "fix": "Run onboard/doctor from your normal desktop terminal."},
]


class TestRender(unittest.TestCase):
    def test_heading_and_row_shape_are_kept(self):
        t = preflight.render(ROWS)
        self.assertEqual(t.splitlines()[0], "preflight:")
        self.assertIn("warn hyprctl", t)          # `warn <id>` on one line
        self.assertIn("fail architecture", t)

    def test_fail_rows_first_then_warn_then_collapsed_passes(self):
        t = preflight.render(ROWS)
        self.assertLess(t.index("fail architecture"), t.index("warn hyprctl"))
        self.assertLess(t.index("warn wtype"), t.index("ok   home"))
        self.assertIn("home, python", t)
        self.assertNotIn("user directory available", t)

    def test_try_under_its_row_and_a_shared_try_is_said_once(self):
        t = preflight.render(ROWS)
        self.assertEqual(t.count("Install separately"), 1)
        self.assertIn("Try: Use Linux x86_64/aarch64.", t)
        self.assertIn("Try: Run onboard/doctor", t)
        self.assertIn("For the other warnings, try: Install separately", t)

    def test_fits_the_width_and_is_plain(self):
        for width in (60, 80, 200):
            t = preflight.render(ROWS, width=width)
            for line in t.splitlines():
                self.assertLessEqual(output.display_width(line),
                                     min(width, 100), line)
            self.assertNotIn("\x1b", t)
            self.assertTrue(t.isascii())

    def test_color_marks_problem_words_only(self):
        t = preflight.render(ROWS, color=True)
        self.assertIn("\x1b[31mfail\x1b[0m", t)
        self.assertIn("\x1b[93mwarn\x1b[0m", t)

    def test_format_rows_is_unchanged_for_update_and_refusals(self):
        self.assertIn("MISS architecture", preflight.format_rows(ROWS))
        self.assertIn("(Try: Use Linux", preflight.refusal(ROWS))


if __name__ == "__main__":
    unittest.main()
