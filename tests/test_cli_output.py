#!/usr/bin/env python3
"""The shared terminal output module (wisp/cli/output.py)."""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp.cli import output as o  # noqa: E402

ROWS = [["hyprctl", "warn", "not found; needed for the push-to-talk bind "
         "and the pointer, install it or run from your desktop terminal"],
        ["ffmpeg", "ok", "/usr/bin/ffmpeg"]]


class TestWidth(unittest.TestCase):
    def test_display_width_counts_wide_and_ignores_escapes(self):
        self.assertEqual(o.display_width("abc"), 3)
        self.assertEqual(o.display_width("\u754c\u754c"), 4)
        self.assertEqual(o.display_width("\x1b[32mok\x1b[0m"), 2)
        self.assertEqual(o.display_width("e\u0301"), 1)

    def test_truncate_uses_display_width_and_an_ascii_ellipsis(self):
        self.assertEqual(o.truncate("abcdefghij", 6), "abc...")
        self.assertEqual(o.truncate("abcdefghij", 6, glyphs=True),
                         "abcde\u2026")
        self.assertEqual(o.truncate("\u754c\u754c\u754c", 5), "\u754c...")
        self.assertEqual(o.truncate("short", 9), "short")
        for n in range(0, 8):
            self.assertLessEqual(o.display_width(o.truncate("x" * 30, n)),
                                 max(n, 0))

    def test_term_width_reads_columns_and_clamps(self):
        self.assertEqual(o.term_width({"COLUMNS": "120"}), 120)
        self.assertEqual(o.term_width({"COLUMNS": "10"}), 40)
        self.assertEqual(o.term_width({"COLUMNS": "900"}), 200)
        self.assertEqual(o.term_width({"COLUMNS": "x"}, default=77), 77)

    def test_table_fits_at_every_width_without_wrapping(self):
        for width in (60, 80, 200):
            with self.subTest(width=width):
                t = o.table(["id", "level", "detail"], ROWS, width=width)
                for line in t.splitlines():
                    self.assertLessEqual(o.display_width(line), width, line)
                self.assertEqual(len(t.splitlines()), 3)
        wide = o.table(["id", "level", "detail"], ROWS, width=200)
        self.assertIn("run from your desktop terminal", wide)

    def test_wide_characters_align(self):
        t = o.table(["name", "x"], [["\u754c\u754c", "1"], ["ab", "2"]],
                    header=False)
        cols = {o.display_width(l.split("  ")[0]) for l in t.splitlines()}
        self.assertEqual(len(cols), 2)    # 4 and 2 wide, padded to one column
        starts = {o.display_width(l[:l.rindex("  ") + 2])
                  for l in t.splitlines()}
        self.assertEqual(len(starts), 1)

    def test_right_align_and_empty_rows(self):
        t = o.table(["k", "n"], [["a", "5"], ["b", "100"]], align="lr")
        self.assertTrue(all(l.endswith(("n", "5", "100")) for l in
                            t.splitlines()))
        self.assertEqual(o.table(["a", "b"], [], header=False), "")
        self.assertEqual(o.table(["a", "b"], []).strip(), "a  b")

    def test_single_giant_cell_is_cut(self):
        t = o.table(["only"], [["x" * 500]], width=60)
        self.assertLessEqual(o.display_width(t.splitlines()[1]), 60)

    def test_wrap_hanging_indent(self):
        lines = o.wrap("one two three four five six", 12, indent="  ")
        self.assertTrue(all(o.display_width(l) <= 12 for l in lines))
        self.assertTrue(all(l.startswith("  ") for l in lines))


class TestGate(unittest.TestCase):
    def test_color_off_cases(self):
        self.assertFalse(o.use_color(False, tty=True, env={"NO_COLOR": "1"}))
        self.assertFalse(o.use_color(False, tty=True, env={"TERM": "dumb"}))
        self.assertFalse(o.use_color(False, tty=False, env={}))
        self.assertFalse(o.use_color(True, tty=True, env={}))
        self.assertTrue(o.use_color(False, tty=True, env={"NO_COLOR": ""}))

    def test_force_color_turns_it_on_but_not_over_no_color(self):
        self.assertTrue(o.use_color(False, tty=False,
                                    env={"FORCE_COLOR": "1"}))
        self.assertFalse(o.use_color(False, tty=False,
                                     env={"FORCE_COLOR": "0"}))
        self.assertFalse(o.use_color(False, tty=True,
                                     env={"FORCE_COLOR": "1",
                                          "NO_COLOR": "1"}))
        self.assertFalse(o.use_color(True, tty=False,
                                     env={"FORCE_COLOR": "1"}))

    def test_glyphs_need_a_utf8_tty(self):
        self.assertTrue(o.use_glyphs(True, {"LANG": "en_US.UTF-8"}))
        self.assertFalse(o.use_glyphs(True, {"LANG": "C"}))
        self.assertFalse(o.use_glyphs(False, {"LANG": "en_US.UTF-8"}))
        self.assertFalse(o.use_glyphs(True, {"LANG": "en_US.UTF-8",
                                             "TERM": "dumb"}))
        self.assertTrue(o.use_glyphs(True, {"LC_ALL": "C.utf8"}))


class TestColor(unittest.TestCase):
    def test_ansi16_by_default(self):
        t = o.table(["a"], [["x"]], tones=[["ok"]], color=True)
        self.assertIn("\x1b[32mx\x1b[0m", t)
        self.assertNotIn("38;2", t)

    def test_only_the_five_tones_paint(self):
        self.assertEqual(o.paint("x", "rainbow"), "x")
        for tone in ("ok", "fail", "warn", "muted", "accent"):
            self.assertIn("\x1b[", o.paint("x", tone))

    def test_no_escapes_when_color_is_off(self):
        t = o.table(["a", "b"], ROWS, tones=[["ok", "fail", "warn"]] * 2)
        self.assertNotIn("\x1b", t)
        self.assertNotIn("\x1b", o.kv([("a", "b")]))
        self.assertNotIn("\x1b", o.summary("t", [(1, "ok", "ok")], 40))

    def test_colored_cells_keep_alignment(self):
        plain = o.table(["a", "b"], [["x", "y"], ["longer", "z"]],
                        tones=[["ok", None]] * 2)
        col = o.table(["a", "b"], [["x", "y"], ["longer", "z"]],
                      tones=[["ok", None]] * 2, color=True)
        self.assertEqual(o.strip_ansi(col), plain)


class TestGuidingLight(unittest.TestCase):
    def test_only_the_current_step_is_lit(self):
        self.assertEqual(o.step_marker("now", True), "\u25cf")
        self.assertEqual(o.step_marker("now", False), "*")
        self.assertEqual(o.step_marker("todo", True), "\u25cb")
        self.assertEqual(o.step_marker("done", True), "done")
        self.assertEqual(o.step_marker("skip", False), "skip")
        steps = [o.step_marker(s, True) for s in
                 ("done", "now", "todo", "todo", "skip")]
        self.assertEqual(sum(1 for s in steps if s == "\u25cf"), 1)

    def test_current_step_is_the_only_ember_text(self):
        self.assertIn("\x1b[1;33m", o.step_marker("now", True, True))
        for s in ("todo", "done", "skip"):
            self.assertNotIn("33m", o.step_marker(s, True, True))

    def test_banner_is_quiet(self):
        for glyphs in (True, False):
            b = o.banner("1.0.0", glyphs)
            self.assertEqual(len(b.splitlines()), 2)
            self.assertIn("wisp", b.splitlines()[0])
            self.assertNotIn("\x1b", b)
        self.assertTrue(o.banner("1.0.0", True).startswith("\u25cf"))
        self.assertTrue(o.banner("1.0.0", False).startswith("* "))


class TestAllowList(unittest.TestCase):
    ALLOWED = set("\u25cf\u25cb\u203a\u00b7\u2026\u2500\u2502")

    def test_glyph_table_is_ascii_or_allow_listed_and_has_ascii_fallback(self):
        for name, (g, a) in o.GLYPHS.items():
            self.assertTrue(set(g) <= self.ALLOWED, name)
            self.assertTrue(a.isascii(), name)

    def test_helpers_emit_no_emoji_or_em_dash(self):
        text = "\n".join([
            o.table(["a", "b"], ROWS, glyphs=True, width=60),
            o.kv([("k", "v" * 90)], width=50, glyphs=True),
            o.summary("wisp doctor", [(3, "ok", "ok"), (2, "warn", "warn")],
                      60, glyphs=True),
            o.banner("1", True),
            " ".join(o.step_marker(s, True) for s in
                     ("now", "todo", "done", "skip", "na"))])
        extra = {ch for ch in text if not ch.isascii()} - self.ALLOWED
        self.assertEqual(extra, set())
        self.assertNotIn("\u2014", text)

    def test_ascii_mode_is_ascii(self):
        text = "\n".join([
            o.kv([("k", "v" * 90)], width=50),
            o.summary("t", [(3, "ok", "ok"), (2, "warn", "warn")], 60),
            o.banner("1"), o.step_marker("now"), o.step_marker("todo")])
        self.assertTrue(text.isascii())


class TestSummary(unittest.TestCase):
    def test_counts_right_aligned_zero_skipped(self):
        s = o.summary("wisp doctor", [(14, "ok", "ok"), (9, "warn", "warn"),
                                      (0, "fail", "fail")], 60)
        self.assertEqual(o.display_width(s), 60)
        self.assertTrue(s.endswith("14 ok, 9 warn"))
        self.assertNotIn("fail", s)


if __name__ == "__main__":
    unittest.main()
