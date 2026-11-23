#!/usr/bin/env python3
"""The one status table.

wisp/status.py is the source; scripts/assets/gen_status.py writes
shell-plugin/lib/status.js. These tests check the rows are complete and
consistent with wisp/copy.py, that the generated file is fresh and agrees
with Python, and that no other QML or JS file keeps its own copy of the
mapping from a status to a word, a tone or a glyph.
"""
import json
import pathlib
import re
import subprocess
import sys
import unittest

import jsnode

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "assets"))

from wisp import copy as wcopy, status as wstatus  # noqa: E402
import gen_status  # noqa: E402

PLUGIN = ROOT / "shell-plugin"
OWNERS = {PLUGIN / "lib" / "status.js", PLUGIN / "lib" / "copy.js"}
ICONS = (ROOT / "shell-plugin" / "lib" / "icons.js").read_text()


class TestRows(unittest.TestCase):
    def test_every_copy_status_has_a_row_and_back(self):
        self.assertEqual(set(wcopy.STATUS), set(wstatus.STATUSES))
        for k in wstatus.STATUSES + wstatus.DERIVED:
            self.assertIn(k, wstatus.ROWS)

    def test_words_are_copy_keys_with_text(self):
        for k, r in wstatus.ROWS.items():
            for f in ("word", "short"):
                self.assertIn(r[f], wcopy.STRINGS, (k, f))

    def test_short_word_is_the_main_word_or_a_prefix(self):
        for k, r in wstatus.ROWS.items():
            word, short = wcopy.STRINGS[r["word"]], wcopy.STRINGS[r["short"]]
            self.assertTrue(word.startswith(short), (k, short, word))
        self.assertEqual(wcopy.STRINGS[wstatus.ROWS["transcribing"]["short"]],
                         "hearing")

    def test_rows_are_well_formed(self):
        from wisp.theme import TOKENS
        creature = set(re.findall(
            r'"([a-z_]+)"', (PLUGIN / "lib" / "creature.js").read_text()
            .split("var STATES = [")[1].split("]")[0]))
        for k, r in wstatus.ROWS.items():
            self.assertIn(r["tone"], wcopy.TONES, k)
            self.assertIn(r["glyph"], ICONS, k)
            self.assertTrue(r["glyph"].startswith("bar-"), k)
            self.assertIn(r["creature"], creature, k)
            for t in (r["mark_token"], r["creature_token"]):
                self.assertTrue(t in TOKENS or t == "inkMuted", (k, t))
            self.assertIn(r["buddy"], ("hidden", "waveform", "spinner",
                                       "triangle", "triangleNeedsYou"), k)
            if r["pill"] is not None:
                self.assertIn(r["pill"]["when"], ("always", "rated"), k)

    def test_idle_and_offline_hide_the_pill(self):
        for k in ("idle", "offline", "suggestion"):
            self.assertIsNone(wstatus.ROWS[k]["pill"], k)

    def test_error_causes_are_copy_keys(self):
        causes = wstatus.ROWS["error"]["causes"]
        self.assertTrue(causes)
        for code, key in causes.items():
            self.assertIn(key, wcopy.STRINGS, code)

    def test_copy_derives_from_the_table(self):
        for s in wstatus.STATUSES:
            r = wstatus.ROWS[s]
            self.assertEqual(wcopy.status_word(s), wcopy.STRINGS[r["word"]])
            self.assertEqual(wcopy.status_tone(s), r["tone"])
            self.assertEqual(wcopy.word_view(s), (wcopy.status_word(s),
                                                  wcopy.status_tone(s)))
        self.assertEqual(wcopy.word_view("acting", "", "", True),
                         ("reconnecting", "muted"))
        self.assertEqual(wcopy.word_view("done", "BLOCKED (x)"),
                         ("blocked", "needsYou"))
        self.assertEqual(wcopy.status_word("bogus"), "offline")

    def test_the_unified_words(self):
        want = {"idle": "ready", "listening": "listening",
                "transcribing": "hearing you", "deciding": "thinking",
                "acting": "working", "speaking": "speaking",
                "awaiting_choice": "your call", "suggestion": "idea",
                "done": "done", "error": "that failed",
                "offline": "offline"}
        self.assertEqual({k: wcopy.status_word(k) for k in want}, want)


class TestOneSourceForStatusLists(unittest.TestCase):
    """The daemon, the reader and the table name the same statuses."""

    def test_daemon_busy_is_the_table_busy(self):
        from wisp import state as wstate
        self.assertEqual(set(wstate.BUSY), set(wstatus.BUSY))

    def test_reader_statuses_are_the_table_statuses_without_offline(self):
        src = (ROOT / "shell-plugin" / "lib" / "state.js").read_text()
        m = re.search(r"var STATUSES = \[(.*?)\]", src, re.S)
        self.assertIsNotNone(m)
        reader = set(re.findall(r'"([a-z_]+)"', m.group(1)))
        self.assertEqual(reader, set(wstatus.STATUSES) - {"offline"})


class TestGenerated(unittest.TestCase):
    def test_status_js_is_fresh(self):
        js = PLUGIN / "lib" / "status.js"
        self.assertEqual(js.read_text(), gen_status.render(),
                         "status.js is stale: run "
                         "python scripts/assets/gen_status.py")

    def test_gen_status_check_mode(self):
        p = subprocess.run([sys.executable, str(
            ROOT / "scripts" / "assets" / "gen_status.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_check_mode_fails_when_stale(self):
        real = gen_status.OUT
        tmp = ROOT / "tests" / "_status_stale.tmp.js"
        try:
            tmp.write_text("stale\n")
            gen_status.OUT = tmp
            self.assertEqual(gen_status.main(["--check"]), 1)
        finally:
            gen_status.OUT = real
            tmp.unlink(missing_ok=True)

    @unittest.skipUnless(jsnode.NODE, "node not installed")
    def test_js_agrees_with_python(self):
        statuses = list(wstatus.STATUSES) + ["bogus", ""]
        results = ("", "BLOCKED (x)", "ACTED ok")
        got = jsnode.call(
            "(function () {"
            f"var S = {json.dumps(statuses)}, R = {json.dumps(results)};"
            "var out = {rows: Status.ROWS, words: [], views: []};"
            "S.forEach(function (s) {"
            "  out.words.push([Status.statusWord(s), Status.statusTone(s)]);"
            "  R.forEach(function (r) { [false, true].forEach(function (st) {"
            "    out.views.push(Status.wordView(s, r, '', st)) }) }) });"
            "return out })()", Status="status")
        self.assertEqual(got["rows"], wstatus.ROWS)
        views = iter(got["views"])
        for s, (word, tone) in zip(statuses, got["words"]):
            self.assertEqual(word, wcopy.status_word(s), s)
            self.assertEqual(tone, wcopy.status_tone(s), s)
            for r in results:
                for stale in (False, True):
                    w, t = wcopy.word_view(s, r, "", stale)
                    self.assertEqual(next(views), {"word": w, "tone": t},
                                     (s, r, stale))


# ---- the static guard: one mapping, in status.js only -----------------

_STATUS = (r"idle|listening|transcribing|deciding|acting|speaking"
           r"|awaiting_choice|suggestion|done|error|offline")
_LITERAL = re.compile(r"\{[^{}]*\}")
_STR_ENTRY = re.compile(r"""\b(%s)\s*:\s*["']""" % _STATUS)
_NESTED = re.compile(
    r"""\b(%s)\s*:\s*\{[^{}]*\b(word|tone|glyph)\s*:""" % _STATUS)
_CASE = re.compile(r"""case\s+["'](%s)["']\s*:\s*return\s+["']""" % _STATUS)
_TERNARY = re.compile(
    r"""\bstatus\s*===?\s*["'](%s)["']\s*\?\s*["']""" % _STATUS)


def violations(text):
    """Places where `text` maps a status string to a word, tone or glyph."""
    out = []
    if "ui.bar.state." in text:
        out.append("ui.bar.state. key")
    for lit in _LITERAL.findall(text):
        if len(_STR_ENTRY.findall(lit)) >= 2:
            out.append("status-keyed string map: " + lit[:60])
    out += ["status-keyed word/tone/glyph: " + m.group(0)[:60]
            for m in _NESTED.finditer(text)]
    out += ["switch mapping: " + m.group(0) for m in _CASE.finditer(text)]
    out += ["ternary mapping: " + m.group(0) for m in _TERNARY.finditer(text)]
    return out


class TestNoDuplicateMaps(unittest.TestCase):
    def test_no_file_outside_status_js_maps_a_status(self):
        found = {}
        for path in sorted(PLUGIN.rglob("*")):
            if path.suffix not in (".js", ".qml") or path in OWNERS:
                continue
            v = violations(path.read_text())
            if v:
                found[str(path.relative_to(ROOT))] = v
        self.assertEqual(found, {}, "map statuses in wisp/status.py only")

    def test_the_guard_catches_the_old_maps(self):
        samples = [
            'var MARK_ICON = { idle: "bar-idle", listening: "bar-listening" }',
            'var T = { error: "fail", offline: "inkMuted", done: "ink" }',
            'view("acting", "act", "ember", "ui.bar.state.acting", {})',
            'var M = { acting: { word: "working", tone: "ember" } }',
            'switch (s) { case "acting": return "working" }',
            'text: status === "acting" ? "working" : "x"',
        ]
        for s in samples:
            self.assertTrue(violations(s), s)

    def test_the_guard_ignores_unrelated_code(self):
        samples = [
            'var LIVE = { listening: true, acting: true, done: true }',
            'var ENERGY = { offline: 0.05, idle: 0.25, error: 0.2 }',
            'var V = { idle: { energy: 0.2, tempo: "flicker" } }',
            'readonly property bool offline: false',
            'if (status === "error") return errorSettled ? "idle" : "x"',
        ]
        for s in samples:
            self.assertEqual(violations(s), [], s)


if __name__ == "__main__":
    unittest.main()
