#!/usr/bin/env python3
"""Error x surface table (W25, Ember U16).

One source of truth per error code: wisp/copy.py ERRORS. This table walks
every code the daemon can publish (errors_codes.CODES) through every
surface that renders it and asserts the surface shows the copy-table
message (and the hint where the surface has room for one):

  pill     word_view            (Companion pill word)
  console  word_view            (StatusLine word)
  bubble   errorMessage + hint  (Bubble.qml reads service.errorMessage/Hint)
  bar      tooltipLines         (BarWidget tooltip: word and hint lines)
  toast    notify.for_code      (W18 notification body)

The QML surfaces get the same strings through lib/copy.js, which
test_copy.py proves is generated from wisp/copy.py; here the JS functions
the surfaces call are executed under node. Offline and stale states get
the same treatment (they are connection states, not codes).
"""
import pathlib
import re
import sys
import unittest

import jsnode

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
COMP = ROOT / "shell-plugin" / "components"

from wisp import copy as wcopy, errors_codes, notify  # noqa: E402

SURFACES = ("pill", "console", "bubble", "bar", "toast")
SILENT_TOAST = {"cancelled"}   # the user stopped it: no toast by design


def js(expr):
    return jsnode.call(expr, Copy="copy", B="bar", S="state")


def render(code, surface):
    """(text lines) the surface shows for an error turn with `code`."""
    if surface in ("pill", "console"):
        return [js(f"Copy.wordView('error','','{code}',false).word")]
    if surface == "bubble":
        return [js(f"Copy.errorMessage('{code}')"),
                js(f"Copy.errorHint('{code}')")]
    if surface == "bar":
        return js(f"""(function(){{
          var wv = Copy.wordView('error','','{code}',false);
          return B.tooltipLines({{health: {{}}}}, {{word: wv.word,
            hint: Copy.errorHint('{code}'), notice: '', stale: false,
            offline: false, ui: Copy.string}});
        }})()""")
    if surface == "toast":
        level, text = notify.for_code(code)
        return [text] if level else []
    raise AssertionError(surface)


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestErrorTable(unittest.TestCase):
    def test_every_daemon_code_is_in_the_copy_table_and_the_js_reader(self):
        codes = js("S.ERROR_CODES")
        self.assertEqual(set(codes), set(errors_codes.CODES))
        self.assertEqual(set(wcopy.ERRORS), set(errors_codes.CODES))
        self.assertEqual(set(js("Object.keys(Copy.ERRORS)")),
                         set(errors_codes.CODES))

    def test_every_code_renders_on_every_surface(self):
        for code in errors_codes.CODES:
            msg, hint = wcopy.ERRORS[code]
            for surface in SURFACES:
                if surface == "toast" and code in SILENT_TOAST:
                    self.assertEqual(render(code, "toast"), [], code)
                    continue
                text = "\n".join(render(code, surface))
                self.assertIn(msg, text, f"{code} on {surface}")
                if hint and surface in ("bubble", "bar", "toast"):
                    self.assertIn(hint, text, f"{code} hint on {surface}")

    def test_toast_text_is_the_copy_text_not_the_fallback_string(self):
        for code in errors_codes.CODES:
            level, text = notify.for_code(code)
            self.assertEqual(text, wcopy.toast_text(code), code)

    def test_error_fallback_string_comes_from_the_same_table(self):
        for code in errors_codes.CODES:
            self.assertEqual(errors_codes.human(code),
                             wcopy.error_message(code), code)

    def test_unknown_code_renders_as_internal_everywhere(self):
        want = wcopy.error_message("internal")
        for surface in ("pill", "console", "bubble", "bar"):
            self.assertIn(want, "\n".join(render("nope_code", surface)))
        level, text = notify.for_code("nope_code")
        self.assertIn(want, text)

    def test_python_and_js_agree_on_the_word_view(self):
        for code in errors_codes.CODES:
            self.assertEqual(
                js(f"Copy.wordView('error','','{code}',false)"),
                dict(zip(("word", "tone"),
                         wcopy.word_view("error", "", code, False))), code)

    def test_error_tone_is_fail_only_for_errors(self):
        self.assertEqual(wcopy.word_view("error", "", "timeout", False)[1],
                         "fail")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestConnectionStates(unittest.TestCase):
    def test_offline_word_and_tooltip(self):
        self.assertEqual(wcopy.word_view("offline", "", "", False),
                         ("offline", "muted"))
        lines = js("""B.tooltipLines({health: {}}, {word: 'offline',
          notice: Copy.string('state.offline'), stale: false, offline: true,
          ui: Copy.string})""")
        self.assertIn(wcopy.string("state.offline"), lines)
        self.assertEqual(lines[-1], wcopy.string("ui.bar.hint.offline"))
        self.assertIn("start wisp", lines[-1])

    def test_stale_busy_reads_reconnecting_never_the_live_word(self):
        for status in ("transcribing", "deciding", "acting"):
            self.assertEqual(wcopy.word_view(status, "", "", True),
                             ("reconnecting", "muted"), status)
            self.assertEqual(
                js(f"Copy.wordView('{status}','','',true)"),
                {"word": "reconnecting", "tone": "muted"})

    def test_stale_flag_never_hides_an_idle_or_error_state(self):
        self.assertEqual(wcopy.word_view("idle", "", "", True)[0], "ready")
        self.assertEqual(wcopy.word_view("error", "", "timeout", True)[0],
                         wcopy.error_message("timeout"))

    def test_stale_bar_tooltip_carries_the_same_word(self):
        wv = js("Copy.wordView('acting','','',true)")
        lines = js("""B.tooltipLines({health: {}}, {word: 'reconnecting',
          notice: '', stale: true, offline: false, ui: Copy.string})""")
        self.assertEqual(lines[0], "wisp: " + wv["word"])

    def test_surfaces_use_the_one_word_view(self):
        """Pill, StatusLine and the bar word all come from the service's
        wordView (copy.wordView), never from a local if-chain."""
        svc = (ROOT / "shell-plugin" / "WispService.qml").read_text()
        self.assertTrue(re.search(r"wordView:\s*Copy\.wordView\(", svc))
        for rel in ("components/Pill.qml", "components/StatusLine.qml",
                    "BarWidget.qml"):
            src = (ROOT / "shell-plugin" / rel).read_text()
            self.assertIn("wordView", src, rel)
            self.assertIsNone(re.search(r"\.errorMessage\s*!==", src),
                              f"{rel} picks the error word itself")
        bubble = (COMP / "Bubble.qml").read_text()
        self.assertIn("service.errorMessage", bubble)
        self.assertIn("service.errorHint", bubble)


if __name__ == "__main__":
    unittest.main()
