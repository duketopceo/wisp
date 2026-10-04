#!/usr/bin/env python3
"""TUI and management app on shared tokens (plan U18)."""
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import config, copy as wcopy, tui  # noqa: E402

SHELL = ROOT / "shells" / "debug" / "shell.qml"
STYLES = {k: i + 100 for i, k in enumerate(
    ("head", "label", "ember", "needsYou", "fail", "ok", "muted", "alert"))}


class FakeWin:
    def __init__(self, h=40, w=100):
        self.h, self.w, self.cells = h, w, []

    def erase(self):
        self.cells = []

    def getmaxyx(self):
        return self.h, self.w

    def addnstr(self, row, col, text, n, attr=0):
        self.cells.append((row, text[:n], attr))

    def refresh(self):
        pass

    def lines(self):
        return [t for _, t, _ in self.cells]


STATE = {
    "status": "acting",
    "transcript": "open the browser",
    "steps": ["launch firefox", "SKIP (launch but no app identified)"],
    "result": "SKIP (unknown app 'zzz')",
    "tasks": {"t1": {"status": "running", "task": "x"}},
}


def render(state=None, offline=False, **kw):
    win = FakeWin()
    with mock.patch("wisp.telemetry.text", return_value="turns 3\nok 2"), \
         mock.patch("wisp.skills.index",
                    return_value=[{"name": "alpha", "tool": True},
                                  {"name": "beta"}]):
        tui._draw(win, state if state is not None else STATE, [], [],
                  offline, STYLES, **kw)
    return win


class TestTuiRender(unittest.TestCase):
    def test_header_is_wisp_plus_copy_status_word(self):
        win = render()
        head = win.lines()[0]
        self.assertTrue(head.startswith("wisp"), head)
        self.assertIn(wcopy.status_word("acting"), head)

    def test_every_status_uses_the_copy_map_word(self):
        for status in wcopy.STATUS:
            head = render({"status": status}).lines()[0]
            self.assertIn(wcopy.status_word(status), head, status)

    def test_status_attr_follows_copy_tone(self):
        for status in ("acting", "awaiting_choice", "error", "done", "idle"):
            win = render({"status": status})
            row, _, attr = win.cells[0]
            self.assertEqual(attr, STYLES[wcopy.status_tone(status)], status)

    def test_no_unicode_icon_glyphs(self):
        for line in render().lines():
            self.assertIsNone(re.search(r"[^\x00-\x7f]", line), line)

    def test_offline_header_uses_offline_word(self):
        head = render({}, offline=True).lines()[0]
        self.assertIn(wcopy.status_word("offline"), head)

    def test_raw_result_strings_are_translated(self):
        text = "\n".join(render().lines())
        self.assertNotIn("SKIP (", text)
        self.assertIn("didn't recognize that app", text)
        self.assertIn("didn't catch which app", text)

    def test_no_em_dashes(self):
        for line in render().lines():
            self.assertNotIn("—", line)


class TestAnsiPalette(unittest.TestCase):
    def test_pairs_use_only_ansi_0_to_15(self):
        pairs = []
        with mock.patch("curses.has_colors", return_value=True), \
             mock.patch("curses.start_color"), \
             mock.patch("curses.use_default_colors"), \
             mock.patch("curses.init_pair",
                        side_effect=lambda n, f, b: pairs.append((f, b))), \
             mock.patch("curses.color_pair", side_effect=lambda n: n << 8), \
             mock.patch("curses.init_color",
                        side_effect=AssertionError("must not redefine")):
            styles = tui._init_styles()
        self.assertTrue(pairs)
        for fg, bg in pairs:
            self.assertTrue(0 <= fg <= 15 or fg == -1, fg)
            self.assertTrue(0 <= bg <= 15 or bg == -1, bg)
        self.assertEqual(set(STYLES) - set(styles), set())

    def test_no_color_terminal_gets_attribute_fallbacks(self):
        with mock.patch("curses.has_colors", return_value=False):
            styles = tui._init_styles()
        self.assertEqual(set(STYLES) - set(styles), set())


class TestManagementApp(unittest.TestCase):
    def setUp(self):
        self.qml = SHELL.read_text()

    def test_no_hex_literal(self):
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", self.qml), [])

    def test_old_background_is_gone(self):
        self.assertNotIn("16161e", self.qml.lower())

    def test_tokens_come_from_the_service_and_follow_theme_name(self):
        # W26: the app reads tokens through WispService (lib/tokens.js over
        # colors.toml); the Commons shim watches theme.name for the swap.
        self.assertIn("readonly property var tk: svc.tokens", self.qml)
        shim = (SHELL.parent / "Commons" / "Color.qml").read_text()
        self.assertIn("theme.name", shim)
        self.assertIn("currentThemePath", shim)

    def test_no_em_dash_or_symbol_icons(self):
        self.assertNotIn("—", self.qml)
        for glyph in "✦✓✗⚠●○▸→✕⚙":
            self.assertNotIn(glyph, self.qml)

    def test_install_places_tokens_and_copy_beside_app(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader(
            "wispd_u18", str(ROOT / "wispd"))
        spec = importlib.util.spec_from_loader("wispd_u18", loader)
        wispd = importlib.util.module_from_spec(spec)
        loader.exec_module(wispd)
        with tempfile.TemporaryDirectory() as td:
            home = pathlib.Path(td)
            with mock.patch.object(config, "HOME", home), \
                 mock.patch.object(wispd.subprocess, "run"), \
                 mock.patch("wisp.platform.current", return_value="linux"):
                wispd.install_files()
            app = home / ".local/opt/wisp/shells/debug"
            for name in ("tokens.js", "copy.js"):
                f = app / name
                self.assertTrue(f.is_file() and not f.is_symlink(), f)
                self.assertEqual(f.read_bytes(),
                                 (ROOT / "shell-plugin/lib" / name).read_bytes())
            # W26: the service, its libs and the view components ride along
            # as real files (the repo links them to shell-plugin/)
            for rel in ("WispService.qml", "lib/state.js", "lib/manage.js",
                        "components/HealthSection.qml",
                        "components/SpendView.qml", "Commons/qmldir"):
                f = app / rel
                self.assertTrue(f.is_file() and not f.is_symlink(), f)
            self.assertEqual((app / "lib/state.js").read_bytes(),
                             (ROOT / "shell-plugin/lib/state.js").read_bytes())


if __name__ == "__main__":
    unittest.main()
